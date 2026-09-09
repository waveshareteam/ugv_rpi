using System.IO;
using System.Net.Http;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace CommandCenter.Core;

/// <summary>
/// Decodes an MJPEG multipart/x-mixed-replace stream (Flask video_feed) into
/// BitmapSource frames on a background thread.
/// </summary>
public sealed class MjpegStreamer : IAsyncDisposable
{
    public event Action<BitmapSource>? Frame;
    public bool Running { get; private set; }

    HttpClient _http;
    string _url;
    CancellationTokenSource? _cts;
    Task? _task;
    int _reconnectDelay = 800;

    public MjpegStreamer(string url)
    {
        _url = url;
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
    }

    public void Start()
    {
        if (_task != null) return;
        _cts = new CancellationTokenSource();
        _task = Task.Run(() => RunAsync(_cts.Token));
    }

    public async ValueTask DisposeAsync()
    {
        _cts?.Cancel();
        try { _http.Dispose(); } catch { }
    }

    async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, _url);
                using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
                resp.EnsureSuccessStatusCode();
                await using var stream = await resp.Content.ReadAsStreamAsync(ct);

                Running = true;
                _reconnectDelay = 800;

                // Parse multipart chunks: find SOI (FFD8) ... EOI (FFD9)
                var jpeg = new MemoryStream();
                bool inJpeg = false;
                var buf = new byte[32 * 1024];
                while (!ct.IsCancellationRequested)
                {
                    int n = await stream.ReadAsync(buf, ct);
                    if (n <= 0) break;
                    for (int i = 0; i < n; i++)
                    {
                        byte b = buf[i];
                        if (!inJpeg)
                        {
                            if (b == 0xFF && i + 1 < n && buf[i + 1] == 0xD8) { inJpeg = true; jpeg.SetLength(0); jpeg.WriteByte(buf[i]); jpeg.WriteByte(buf[i + 1]); i++; }
                        }
                        else
                        {
                            jpeg.WriteByte(b);
                            if (b == 0xD9 && jpeg.Length >= 2 && jpeg.GetBuffer()[jpeg.Length - 2] == 0xFF)
                            {
                                inJpeg = false;
                                DecodeFrame(jpeg.ToArray());
                            }
                        }
                    }
                }
            }
            catch (OperationCanceledException) { break; }
            catch { }
            Running = false;
            try { await Task.Delay(_reconnectDelay, ct); } catch { }
            _reconnectDelay = Math.Min(_reconnectDelay * 2, 8000);
        }
    }

    void DecodeFrame(byte[] jpegBytes)
    {
        try
        {
            var img = new BitmapImage();
            using var ms = new MemoryStream(jpegBytes);
            img.BeginInit();
            img.CacheOption = BitmapCacheOption.OnLoad;
            img.StreamSource = ms;
            img.EndInit();
            img.Freeze();                 // cross-thread safe
            Frame?.Invoke(img);
        }
        catch { /* bad frame */ }
    }
}
