using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace CommandCenter.Core;

/// <summary>
/// Minimal Socket.IO v4 client over a raw WebSocket (no SocketIOClient package).
/// Supports: handshake (engine.io "open" packet), namespace connect ("40"),
/// emitting "json"/"message" events ("42[...]"), receiving event messages,
/// ping/pong (engine.io), and auto-reconnect with backoff.
/// </summary>
public sealed class SocketIoClient : IAsyncDisposable
{
    public event Action<string, JsonElement>? EventReceived;   // (event name, args[0])
    public event Action<bool>? ConnectedChanged;

    public bool IsConnected { get; private set; }

    readonly Uri _wsUri;          // ws://host:port/socket.io/?EIO=4&transport=websocket
    readonly string _namespace;
    ClientWebSocket? _ws;
    CancellationTokenSource? _cts;
    Task? _loop;
    int _reconnectDelay = 1000;
    readonly SemaphoreSlim _sendLock = new(1, 1);

    public SocketIoClient(string baseUrl, string ns)
    {
        var http = new Uri(baseUrl);
        var ws = $"ws://{http.Host}:{http.Port}/socket.io/?EIO=4&transport=websocket";
        _wsUri = new Uri(ws);
        _namespace = ns;
    }

    public void Start()
    {
        if (_loop != null) return;
        _cts = new CancellationTokenSource();
        _loop = Task.Run(() => RunAsync(_cts.Token));
    }

    public async ValueTask DisposeAsync()
    {
        _cts?.Cancel();
        try { if (_ws != null) await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", CancellationToken.None); } catch { }
    }

    public void Emit(string eventName, object payload) => _ = EmitAsync(eventName, payload);

    public async Task EmitAsync(string eventName, object payload, CancellationToken ct = default)
    {
        var ws = _ws;
        if (ws == null || ws.State != WebSocketState.Open || !IsConnected) return;
        string json = payload switch
        {
            string s => s,
            _ => JsonSerializer.Serialize(payload)
        };
        // socket.io EVENT packet: 42<namespace>,["event",args...]
        string pkt = $"42{_namespace},[\"{eventName}\",{json}]";
        var bytes = Encoding.UTF8.GetBytes(pkt);
        await _sendLock.WaitAsync(ct);
        try
        {
            await ws.SendAsync(bytes, WebSocketMessageType.Text, true, ct);
        }
        catch { _ = Task.Run(ForceReconnect); }
        finally { _sendLock.Release(); }
    }

    async void ForceReconnect()
    {
        try { _ws?.Abort(); } catch { }
    }

    async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                _ws = new ClientWebSocket();
                _ws.Options.KeepAliveInterval = TimeSpan.FromSeconds(10);
                await _ws.ConnectAsync(_wsUri, ct);

        // socket.io v4: server sends "0{open json}"; client replies "40<ns>"
        string open = await ReceiveTextAsync(ct);
        if (open == null || !open.StartsWith("0")) throw new Exception("no engine.io open");
        await SendRawAsync("40" + _namespace, ct);

                IsConnected = true;
                _reconnectDelay = 1000;
                ConnectedChanged?.Invoke(true);

                // run receive loop until closed
                var buf = new byte[64 * 1024];
                var sb = new StringBuilder();
                while (!ct.IsCancellationRequested && _ws.State == WebSocketState.Open)
                {
                    var res = await _ws.ReceiveAsync(new ArraySegment<byte>(buf), ct);
                    if (res.MessageType == WebSocketMessageType.Close) break;
                    sb.Append(Encoding.UTF8.GetString(buf, 0, res.Count));
                    if (!res.EndOfMessage) continue;
                    string msg = sb.ToString();
                    sb.Clear();
                    HandlePacket(msg, ct);
                }
            }
            catch (OperationCanceledException) { break; }
            catch { /* fallthrough to reconnect */ }

            IsConnected = false;
            ConnectedChanged?.Invoke(false);
            try { _ws?.Dispose(); } catch { }
            _ws = null;
            try { await Task.Delay(_reconnectDelay, ct); } catch { }
            _reconnectDelay = Math.Min(_reconnectDelay * 2, 8000);
        }
    }

    void HandlePacket(string msg, CancellationToken ct)
    {
        if (msg.Length == 0) return;
        char type = msg[0];
        switch (type)
        {
            case '2':                    // engine.io ping → pong
                _ = SendRawAsync("3", ct);
                break;
            case '4':                    // socket.io packet
                if (msg.StartsWith("42"))
                {
                    int comma = msg.IndexOf(',');
                    if (comma < 0) return;
                    string ns = msg[2..comma];
                    if (ns != _namespace) return;
                    string arr = msg[(comma + 1)..];
                    try
                    {
                        using var doc = JsonDocument.Parse(arr);
                        var root = doc.RootElement;
                        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() >= 2)
                        {
                            string ev = root[0].GetString() ?? "";
                            EventReceived?.Invoke(ev, root[1].Clone());
                        }
                    }
                    catch { /* not json */ }
                }
                break;
        }
    }

    async Task SendRawAsync(string pkt, CancellationToken ct)
    {
        var ws = _ws;
        if (ws?.State != WebSocketState.Open) return;
        var bytes = Encoding.UTF8.GetBytes(pkt);
        try
        {
            await _sendLock.WaitAsync(ct);
            try { await ws.SendAsync(bytes, WebSocketMessageType.Text, true, ct); }
            finally { _sendLock.Release(); }
        }
        catch { }
    }

    async Task<string?> ReceiveTextAsync(CancellationToken ct)
    {
        var ws = _ws;
        if (ws == null) return null;
        var buf = new byte[64 * 1024];
        var sb = new StringBuilder();
        while (true)
        {
            var res = await ws.ReceiveAsync(buf, ct);
            if (res.MessageType == WebSocketMessageType.Close) return null;
            sb.Append(Encoding.UTF8.GetString(buf, 0, res.Count));
            if (res.EndOfMessage) return sb.ToString();
        }
    }
}
