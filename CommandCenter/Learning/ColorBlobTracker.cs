using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace CommandCenter.Learning;

/// <summary>
/// Lightweight object detector: finds the bounding box of the largest blob of a
/// target hue in the latest video frame (downsampled). Feeds the Follow-Object
/// autopilot without any ML dependencies. Throttled internally.
/// </summary>
public class ColorBlobTracker
{
    public double TargetHue { get; set; } = 0;         // 0..360
    public double HueTolerance { get; set; } = 25;     // degrees
    public double MinSaturation { get; set; } = 0.35;
    public double MinValue { get; set; } = 0.25;
    public bool Enabled { get; set; } = true;

    public System.Drawing.RectangleF[] LatestBoxes { get; private set; } = Array.Empty<System.Drawing.RectangleF>();
    public int LastBlobPixels { get; private set; }

    DateTime _lastRun = DateTime.MinValue;
    readonly byte[] _px = new byte[64 * 48 * 4];

    const int W = 64, H = 48;

    public void Feed(BitmapSource frame)
    {
        if (!Enabled || frame == null) return;
        if ((DateTime.UtcNow - _lastRun).TotalMilliseconds < 66) return;   // ≤15 fps
        _lastRun = DateTime.UtcNow;

        try
        {
            var small = new FormatConvertedBitmap(frame, PixelFormats.Bgra32, null, 0);
            small.CopyPixels(_px, W * 4, 0);
        }
        catch { return; }

        int minX = W, maxX = -1, minY = H, maxY = -1, count = 0;
        for (int y = 0; y < H; y++)
        {
            for (int x = 0; x < W; x++)
            {
                int i = (y * W + x) * 4;
                double b = _px[i] / 255.0, g = _px[i + 1] / 255.0, r = _px[i + 2] / 255.0;
                double max = Math.Max(r, Math.Max(g, b)), min = Math.Min(r, Math.Min(g, b));
                if (max < MinValue || max - min < MinSaturation * max) continue;
                double hue = max == min ? 0 :
                    max == r ? 60 * (((g - b) / (max - min) + 6) % 6) :
                    max == g ? 60 * ((b - r) / (max - min) + 2) :
                               60 * ((r - g) / (max - min) + 4);
                double dh = Math.Abs(hue - TargetHue);
                if (dh > 180) dh = 360 - dh;
                if (dh <= HueTolerance)
                {
                    count++;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }

        LastBlobPixels = count;
        LatestBoxes = count >= 6 && maxX >= minX
            ? new[] { new System.Drawing.RectangleF(minX / (float)W, minY / (float)H,
                     (maxX - minX + 1) / (float)W, (maxY - minY + 1) / (float)H) }
            : Array.Empty<System.Drawing.RectangleF>();
    }
}
