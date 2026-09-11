using System.IO;
using System.Text.Json;

namespace CommandCenter.Learning;

/// <summary>
/// The "self-learning" drive brain:
///  - follows a learned PathPlan (replay) or drives by reactive lidar following,
///  - learns an obstacle memory while driving and uses it to bias heading choice,
///  - object-follow mode: steers toward the largest detection box sent from the robot's CV.
/// Runs on its own thread; commands the robot through a callback.
/// </summary>
public class AutoPilot
{
    public enum Mode { Off, Reactive, Replay, FollowObject }
    public readonly record struct Frame(Behavior Mode, double L, double R, string Reason);
    public enum Behavior { Cruise, TurnLeft, TurnRight, Slow, AvoidLeft, AvoidRight, Stop, Seek }

    readonly Func<double, double, Task> _drive;
    readonly Func<(double angle, double dist)[]> _getScan;
    readonly Func<System.Drawing.RectangleF[]> _getDetections;
    readonly ObstacleMemory _memory;
    CancellationTokenSource? _cts;
    Task? _loop;

    public Mode CurrentMode { get; private set; } = Mode.Off;
    public string LastDecision { get; private set; } = "off";
    public ObstacleMemory Memory => _memory;

    // tunables
    public double CruiseSpeed = 0.35;        // fraction of max
    public double DangerM = 0.55;            // brake/turn threshold
    public double LookAheadM = 1.1;          // heading evaluation distance
    public double GoalHeadingDeg = 0;        // reactive: keep this heading
    public double WallM = 1.6;               // corridor half-width for memory bias

    public AutoPilot(Func<double, double, Task> drive,
                     Func<(double angle, double dist)[]> getScan,
                     Func<System.Drawing.RectangleF[]> getDetections,
                     ObstacleMemory memory)
    {
        _drive = drive; _getScan = getScan; _getDetections = getDetections; _memory = memory;
    }

    public void Start(Mode mode, PathPlan? replay = null)
    {
        Stop();
        CurrentMode = mode;
        _cts = new CancellationTokenSource();
        var plan = replay;
        _loop = Task.Run(() => mode switch
        {
            Mode.Reactive => ReactiveLoop(_cts.Token),
            Mode.Replay when plan != null => ReplayLoop(plan, _cts.Token),
            Mode.FollowObject => FollowLoop(_cts.Token),
            _ => Task.CompletedTask
        });
    }

    public void Stop()
    {
        _cts?.Cancel();
        try { _drive(0, 0).Wait(400); } catch { }
        CurrentMode = Mode.Off;
        LastDecision = "stopped";
    }

    // ─────────── reactive: lidar corridor following with learned memory ───────────
    async Task ReactiveLoop(CancellationToken ct)
    {
        var headings = new[] { 0, 15, -15, 30, -30, 45, -45, 60, -60, 80, -80, 110, -110 };
        while (!ct.IsCancellationRequested)
        {
            var scan = _getScan();
            _memory.Observe(scan, 6.0);

            double front = MinRange(scan, -25, 25);
            if (front < DangerM)
            {
                double left = MinRange(scan, 25, 80);
                double right = MinRange(scan, -80, -25);
                if (left > right) { await _drive(0.25, 0.55); LastDecision = $"front {front:0.00}m → avoid right-block, turn left (L{left:0.0}/R{right:0.0})"; }
                else { await _drive(0.55, 0.25); LastDecision = $"front {front:0.00}m → turn right"; }
                await Task.Delay(140, ct);
                continue;
            }

            // score headings: free space in lidar + learned clearance from memory
            double best = 0; double bestScore = double.MinValue; string why = "cruise";
            foreach (var h in headings)
            {
                double hr = h * Math.PI / 180;
                double lidarClear = 1.0 - CountBlocked(scan, hr, LookAheadM, 0.4) / 9.0;
                double memClear = _memory.Clearance(hr, LookAheadM);
                double goalBias = -Math.Abs(h - GoalHeadingDeg) / 180.0;      // prefer goal heading
                double score = 2.0 * lidarClear + 1.0 * memClear + 0.6 * goalBias;
                if (score > bestScore) { bestScore = score; best = h; }
            }
            double spd = CruiseSpeed;
            if (Math.Abs(best) > 55) { spd *= 0.55; why = "sharp turn"; }
            else if (front < DangerM * 2) { spd *= 0.7; why = "near obstacle"; }
            double turn = best / 90.0;                       // −1..+1
            double l = spd * (turn > 0 ? 1 : 1 - Math.Abs(turn));
            double r = spd * (turn < 0 ? 1 : 1 - Math.Abs(turn));
            await _drive(l, r);
            LastDecision = $"heading {best:+0;-0}° spd {spd:0.00} ({why}) mem {_memory.BusyCells}c";
            await Task.Delay(140, ct);
        }
    }

    static double MinRange((double angle, double dist)[] scan, double a1, double a2)
    {
        double best = double.MaxValue;
        foreach (var (a, d) in scan)
        {
            double deg = (a + Math.PI) * 180 / Math.PI;         // normalise like the UI
            if (deg > a1 && deg < a2 && d > 0 && d < best) best = d / 1000.0;
        }
        return best == double.MaxValue ? 99 : best;
    }

    static int CountBlocked((double angle, double dist)[] scan, double headingRad, double rangeM, double halfWidthRad)
    {
        int blocked = 0;
        foreach (var (a, d) in scan)
        {
            double ang = a + Math.PI;
            if (Math.Abs(ang - headingRad) > halfWidthRad) continue;
            if (d > 0 && d < rangeM * 1000) blocked++;
        }
        return blocked;
    }

    // ─────────── replay: follow a learned path, with obstacle aborts ───────────
    async Task ReplayLoop(PathPlan plan, CancellationToken ct)
    {
        LastDecision = $"replaying {plan.Steps.Count} steps ({plan.TotalSeconds:0.0}s)";
        foreach (var s in plan.Steps)
        {
            if (ct.IsCancellationRequested) break;
            var scan = _getScan();
            _memory.Observe(scan, 6.0);
            double front = MinRange(scan, -25, 25);
            if (front < DangerM)
            {
                LastDecision = $"replay aborted: obstacle {front:0.00}m ahead";
                await _drive(0, 0);
                return;
            }
            await _drive(s.L, s.R);
            await Task.Delay(TimeSpan.FromSeconds(s.Seconds), ct);
        }
        await _drive(0, 0);
        LastDecision = "replay finished";
    }

    // ─────────── object follow: steer toward largest CV box ───────────
    async Task FollowLoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            var boxes = _getDetections();
            if (boxes.Length == 0)
            {
                await _drive(0, 0);
                LastDecision = "no target — waiting";
                await Task.Delay(300, ct);
                continue;
            }
            var biggest = boxes.OrderByDescending(b => b.Width * b.Height).First();
            float cx = biggest.X + biggest.Width / 2;             // 0..1 of frame
            float err = cx - 0.5f;                                // <0 target left
            double turn = Math.Clamp(err * 2.0, -1, 1);
            double distProxy = biggest.Height;                    // bigger box = closer
            double fwd = Math.Clamp((0.45f - distProxy) * 2.0, -0.4, 0.6);
            double l = fwd - turn * 0.5, r = fwd + turn * 0.5;
            await _drive(Math.Clamp(l, -0.5, 0.5), Math.Clamp(r, -0.5, 0.5));
            LastDecision = $"follow box {biggest.Width * 100:0}%w err {err:+0.00;-0.00} → L {l:0.00} R {r:0.00}";
            await Task.Delay(150, ct);
        }
    }
}
