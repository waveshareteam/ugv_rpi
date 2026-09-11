namespace CommandCenter.Learning;

/// <summary>
/// Persistent obstacle memory: a coarse occupancy grid around the robot learned
/// from successive lidar scans. Cells accumulate hit counts; stale cells decay.
/// This is what lets the driver/autopilot prefer corridors it has seen clear before.
/// </summary>
public class ObstacleMemory
{
    public const int Size = 121;                 // cells per side (−6..+6 m at 10 cm)
    public const double CellM = 0.10;
    readonly ushort[,] _hits = new ushort[Size, Size];
    readonly DateTime[,] _last = new DateTime[Size, Size];

    static (int x, int y) Cell(double mx, double my)
    {
        int cx = Size / 2 + (int)Math.Round(mx / CellM);
        int cy = Size / 2 - (int)Math.Round(my / CellM);   // +y forward → up in grid
        return (Math.Clamp(cx, 0, Size - 1), Math.Clamp(cy, 0, Size - 1));
    }

    /// <summary>Feed one scan (angle/distance as in the web API, robot frame).</summary>
    public void Observe(IEnumerable<(double angleRad, double distMm)> scan, double rangeM)
    {
        var now = DateTime.UtcNow;
        foreach (var (a, d) in scan)
        {
            if (d <= 0 || d > rangeM * 1000) continue;
            double ang = a + Math.PI;                        // same normalisation as the radar
            double mx = (d / 1000.0) * Math.Sin(ang);
            double my = (d / 1000.0) * Math.Cos(ang);
            var (cx, cy) = Cell(mx, my);
            if (_hits[cx, cy] < ushort.MaxValue) _hits[cx, cy]++;
            _last[cx, cy] = now;
        }
        Decay(now);
    }

    void Decay(DateTime now)
    {
        // cheap probabilistic decay: each cell older than 30 s loses a hit every minute
        for (int x = 0; x < Size; x++)
            for (int y = 0; y < Size; y++)
                if (_hits[x, y] > 0 && (now - _last[x, y]).TotalSeconds > 30)
                {
                    _hits[x, y]--;
                    _last[x, y] = now - TimeSpan.FromSeconds(30);
                }
    }

    /// <summary>Is this robot-frame point (metres, +y forward) known-blocked?</summary>
    public bool IsBlocked(double mx, double my, double minHits = 3)
    {
        var (cx, cy) = Cell(mx, my);
        return _hits[cx, cy] >= minHits;
    }

    /// <summary>Clearance estimate (0..1) for a candidate heading at radius r metres.</summary>
    public double Clearance(double headingRad, double r, double halfWidthRad = 0.35)
    {
        int samples = 12;
        int blocked = 0;
        for (int i = 0; i < samples; i++)
        {
            double a = headingRad + (i - samples / 2.0) / (samples / 2.0) * halfWidthRad;
            if (IsBlocked(r * Math.Sin(a), r * Math.Cos(a))) blocked++;
        }
        return 1.0 - blocked / (double)samples;
    }

    /// <summary>Cells for rendering (robot frame, metres) with a hit count floor.</summary>
    public IEnumerable<(double mx, double my, ushort hits)> Cells(double minHits = 1)
    {
        for (int x = 0; x < Size; x++)
            for (int y = 0; y < Size; y++)
                if (_hits[x, y] >= minHits)
                    yield return ((x - Size / 2) * CellM, (Size / 2 - y) * CellM, _hits[x, y]);
    }

    public int BusyCells => _hits.Cast<ushort>().Count(h => h > 0);
}
