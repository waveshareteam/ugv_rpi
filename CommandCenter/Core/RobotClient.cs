using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Windows.Media.Imaging;

namespace CommandCenter.Core;

/// <summary>High-level facade over the robot's REST + Socket.IO + MJPEG surface.</summary>
public sealed class RobotClient : IAsyncDisposable
{
    public RobotState State { get; } = new();
    public SocketIoClient Ctrl { get; private set; } = null!;    // /ctrl: telemetry 'update', cmd 'message'
    public SocketIoClient Json { get; private set; } = null!;    // /json: drive 'json' channel
    public MjpegStreamer Video { get; private set; } = null!;

    HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(6) };
    CancellationTokenSource _cts = new();

    public void Connect(string baseUrl)
    {
        State.BaseUrl = baseUrl;
        Ctrl?.DisposeAsync().AsTask().Wait(200);
        Json?.DisposeAsync().AsTask().Wait(200);
        Video?.DisposeAsync();

        Ctrl = new SocketIoClient(baseUrl, "/ctrl");
        Json = new SocketIoClient(baseUrl, "/json");
        Video = new MjpegStreamer(baseUrl + "/video_feed");

        Ctrl.EventReceived += OnCtrlEvent;
        Json.EventReceived += OnJsonEvent;
        Ctrl.ConnectedChanged += up => { if (up) { Ctrl.Emit("request_data", new { }); } State.Connected = up; };
        Json.ConnectedChanged += up => { State.Connected = State.Connected || up; };
        Video.Frame += f => { LastFrame = f; VideoFrame?.Invoke(f); };

        Ctrl.Start();
        Json.Start();
        Video.Start();

        _ = Task.Run(() => PollLoops(_cts.Token));
        _ = FetchConfigAsync();
        _ = RefreshCamerasAsync();
    }

    public event Action<BitmapSource>? VideoFrame;
    public event Action? CamerasChanged;
    public event Action<double, double>? CommandSent;

    public BitmapSource? LastFrame { get; private set; }
    public bool WasDriving { get; private set; }

    // ────────────────────────── REST ──────────────────────────
    async Task<JsonElement> GetJsonAsync(string path)
    {
        var resp = await _http.GetAsync(State.BaseUrl + path, _cts.Token);
        resp.EnsureSuccessStatusCode();
        await using var s = await resp.Content.ReadAsStreamAsync(_cts.Token);
        using var doc = await JsonDocument.ParseAsync(s, cancellationToken: _cts.Token);
        return doc.RootElement.Clone();
    }

    public async Task<JsonElement> PostFormAsync(string path, Dictionary<string, string> form)
    {
        using var content = new FormUrlEncodedContent(form);
        var resp = await _http.PostAsync(State.BaseUrl + path, content, _cts.Token);
        resp.EnsureSuccessStatusCode();
        await using var s = await resp.Content.ReadAsStreamAsync(_cts.Token);
        using var doc = await JsonDocument.ParseAsync(s, cancellationToken: _cts.Token);
        return doc.RootElement.Clone();
    }

    public Task<JsonElement> RetryCameraAsync() => PostFormAsync("/retry_camera", new Dictionary<string, string>());
    public Task<JsonElement> SetAvoidanceAsync(bool on) => PostFormAsync("/lidar_avoidance", new() { ["enable"] = on ? "true" : "false" });

    /// <summary>Grab the most recent video frame as JPEG bytes (falls back to pulling one from the stream).</summary>
    public async Task<byte[]> SnapshotJpegAsync()
    {
        if (LastFrame != null)
        {
            var enc = new JpegBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(LastFrame));
            using var ms = new MemoryStream();
            enc.Save(ms);
            return ms.ToArray();
        }
        // no decoded frame yet — pull one straight from the MJPEG stream
        using var resp = await _http.GetAsync(State.BaseUrl + "/video_feed", HttpCompletionOption.ResponseHeadersRead, _cts.Token);
        await using var s = await resp.Content.ReadAsStreamAsync(_cts.Token);
        var buf = new MemoryStream();
        var chunk = new byte[32 * 1024];
        var deadline = DateTime.UtcNow.AddSeconds(2);
        while (DateTime.UtcNow < deadline && buf.Length < 4_000_000)
        {
            int n = await s.ReadAsync(chunk, _cts.Token);
            if (n <= 0) break;
            buf.Write(chunk, 0, n);
        }
        var data = buf.ToArray();
        for (int i = 0; i < data.Length - 1; i++)
        {
            if (data[i] == 0xFF && data[i + 1] == 0xD8)
                for (int j = i + 2; j < data.Length - 1; j++)
                    if (data[j] == 0xFF && data[j + 1] == 0xD9)
                        return data[i..(j + 2)];
            if (data[i] == 0xFF && data[i + 1] == 0xD8) i++;   // skip past SOI scan start
        }
        throw new InvalidOperationException("no frame available");
    }

    public async Task FetchConfigAsync()
    {
        try
        {
            var c = await GetJsonAsync("/config");
            var args = c.GetProperty("args_config");
            State.MaxSpeed = args.GetProperty("max_speed").GetDouble();
            State.SlowSpeed = args.GetProperty("slow_speed").GetDouble();
            var cmd = c.GetProperty("cmd_config");
            State.CmdMotion = cmd.GetProperty("cmd_movition_ctrl").GetInt32();
            State.CmdGimbal = cmd.GetProperty("cmd_gimbal_ctrl").GetInt32();
            var code = c.GetProperty("code");
            State.CmdLightsHead = code.GetProperty("base_ct").GetInt32();
            State.CmdCvNone = code.GetProperty("cv_none").GetInt32();
            State.CmdCvFace = code.GetProperty("cv_face").GetInt32();
            State.CmdCvObjects = code.GetProperty("cv_objs").GetInt32();
            State.CmdCvColor = code.GetProperty("cv_clor").GetInt32();
            State.CmdCvMotion = code.GetProperty("cv_moti").GetInt32();
            State.CmdCvTrack = code.GetProperty("cv_auto").GetInt32();
        }
        catch { /* defaults already set */ }
    }

    public async Task RefreshCamerasAsync()
    {
        try
        {
            var j = await GetJsonAsync("/camera_list");
            State.Cameras.Clear();
            foreach (var cam in j.GetProperty("cameras").EnumerateArray())
            {
                State.Cameras.Add(new CameraInfo
                {
                    Index = cam.GetProperty("index").GetInt32(),
                    Name = cam.GetProperty("name").GetString() ?? "?",
                    InUse = cam.GetProperty("in_use").GetBoolean()
                });
            }
            State.ActiveCamera = j.TryGetProperty("active", out var a) ? a.GetInt32() : -1;
            CamerasChanged?.Invoke();
        }
        catch { /* older server without /camera_list */ }
    }

    public Task<JsonElement> SelectCameraAsync(int index) => PostFormAsync("/select_camera", new() { ["index"] = index.ToString() });

    // ────────────────────────── socket events ──────────────────────────
    void OnCtrlEvent(string ev, JsonElement data)
    {
        if (ev != "update") return;
        try
        {
            if (data.TryGetProperty("CPU", out var cpu)) State.Cpu = cpu.GetDouble();
            if (data.TryGetProperty("RAM", out var ram)) State.Ram = ram.GetDouble();
            if (data.TryGetProperty("base_voltage", out var v)) State.Volt = v.GetDouble();
            if (data.TryGetProperty("RSSI", out var r)) State.Rssi = r.GetDouble();
            if (data.TryGetProperty("temp", out var t)) State.Temp = t.GetDouble();
        }
        catch { }
    }

    void OnJsonEvent(string ev, JsonElement data)
    {
        // The /json namespace echoes acks; nothing critical today.
    }

    // ────────────────────────── drive commands ──────────────────────────
    void SendJson(object payload) => Json.Emit("json", payload);

    /// <summary>Drive with per-wheel values in the web-app convention (-max..max). L=left track speed, R=right.</summary>
    public void Drive(double l, double r)
    {
        SendJson(new { T = State.CmdMotion, L = Math.Round(l, 3), R = Math.Round(r, 3) });
        WasDriving = Math.Abs(l) > 0.001 || Math.Abs(r) > 0.001;
        CommandSent?.Invoke(l, r);
    }

    /// <summary>Gimbal relative move in stick pixels (mirrors control.js: X=dx/2.5, Y=-dy/2.5).</summary>
    public void Gimbal(double dx, double dy) => SendJson(new { T = State.CmdGimbal, X = Math.Round(dx / 2.5, 2), Y = Math.Round(-dy / 2.5, 2), SPD = 0, ACC = 128 });

    public void Stop() => Drive(0, 0);
    public void LightsToggle() => Ctrl.Emit("message", System.Text.Json.JsonSerializer.Serialize(new { A = State.CmdLightsHead }));
    public void CvMode(int code) => Ctrl.Emit("message", System.Text.Json.JsonSerializer.Serialize(new { A = code }));

    // ────────────────────────── polling loops ──────────────────────────
    async Task PollLoops(CancellationToken ct)
    {
        var lidarTimer = new PeriodicTimer(TimeSpan.FromMilliseconds(500));
        var statusTimer = new PeriodicTimer(TimeSpan.FromSeconds(2));

        _ = Task.Run(async () =>
        {
            while (await statusTimer.WaitForNextTickAsync(ct))
            {
                try
                {
                    var st = await GetJsonAsync("/lidar_status");
                    State.AvoidActive = st.GetProperty("avoidance_active").GetBoolean();
                    State.LidarHw = st.GetProperty("hw_connected").GetBoolean();
                }
                catch { }
            }
        });

        while (await lidarTimer.WaitForNextTickAsync(ct))
        {
            if (ct.IsCancellationRequested) break;
            try
            {
                var p = await GetJsonAsync("/lidar_points");
                var angles = p.GetProperty("angles");
                var dist = p.GetProperty("distances");
                var scan = new List<(double, double)>();
                int n = Math.Min(angles.GetArrayLength(), dist.GetArrayLength());
                double minM = double.MaxValue; double minDeg = 0;
                for (int i = 0; i < n; i++)
                {
                    double a = angles[i].GetDouble(), d = dist[i].GetDouble();
                    if (d <= 0 || d > 12000) continue;
                    scan.Add((a, d));
                    if (d < minM) { minM = d; minDeg = a * 180.0 / Math.PI; }
                }
                State.LidarScan = scan;
                State.LidarMinM = minM == double.MaxValue ? 0 : minM / 1000.0;
                State.LidarNearestDeg = minDeg;
                State.LidarSummary = n == 0 ? "no scan data" : $"{n} pts, nearest {State.LidarMinM:0.00} m @ {minDeg:0}°";
            }
            catch { }
        }
    }

    public async ValueTask DisposeAsync()
    {
        _cts.Cancel();
        try { Stop(); } catch { }
        await Ctrl.DisposeAsync();
        await Json.DisposeAsync();
        await Video.DisposeAsync();
    }
}
