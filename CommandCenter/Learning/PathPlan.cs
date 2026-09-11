using System.IO;
using System.Text.Json;

namespace CommandCenter.Learning;

/// <summary>
/// A recorded drive path: a sequence of (left, right, seconds) commands.
/// Recorded from real driving, refinable (smoothing), replayable with a speed factor.
/// </summary>
public class PathPlan
{
    public string Name { get; set; } = "path";
    public DateTime CreatedUtc { get; set; } = DateTime.UtcNow;
    public List<PathStep> Steps { get; set; } = new();

    public class PathStep
    {
        public double L { get; set; }
        public double R { get; set; }
        public double Seconds { get; set; }
        public PathStep() { }
        public PathStep(double l, double r, double sec) { L = l; R = r; Seconds = sec; }
    }

    public double TotalSeconds => Steps.Sum(s => s.Seconds);

    public static string Dir => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "RobotCommandCenter", "paths");

    public void Save(string? name = null)
    {
        if (name != null) Name = name;
        Directory.CreateDirectory(Dir);
        var json = JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(Path.Combine(Dir, Name + ".json"), json);
    }

    public static PathPlan? Load(string file)
    {
        try { return JsonSerializer.Deserialize<PathPlan>(File.ReadAllText(file)); }
        catch { return null; }
    }

    public static List<(string name, string file)> Saved()
    {
        Directory.CreateDirectory(Dir);
        return Directory.GetFiles(Dir, "*.json").Select(f => (Path.GetFileNameWithoutExtension(f), f)).ToList();
    }

    /// <summary>
    /// Refinement pass: merges runs of similar commands and smooths transitions.
    /// Removes hand-jitter from recorded paths so replays are cleaner than the teach run.
    /// </summary>
    public PathPlan Refined()
    {
        var outPlan = new PathPlan { Name = Name + "_refined" };
        // 1) merge consecutive steps with same sign & similar magnitude (±8%)
        var merged = new List<PathStep>();
        foreach (var s in Steps)
        {
            if (merged.Count > 0 &&
                Math.Sign(merged[^1].L) == Math.Sign(s.L) &&
                Math.Sign(merged[^1].R) == Math.Sign(s.R) &&
                Math.Abs(merged[^1].L - s.L) <= 0.08 * Math.Max(0.2, Math.Abs(merged[^1].L)) &&
                Math.Abs(merged[^1].R - s.R) <= 0.08 * Math.Max(0.2, Math.Abs(merged[^1].R)))
            {
                merged[^1].Seconds += s.Seconds;
                merged[^1].L = (merged[^1].L + s.L) / 2;
                merged[^1].R = (merged[^1].R + s.R) / 2;
            }
            else merged.Add(new PathStep(s.L, s.R, s.Seconds));
        }
        // 2) drop sub-120ms dithers (hand jitter between two directions)
        merged = merged.Where(s => s.Seconds >= 0.12 || (s.L == 0 && s.R == 0)).ToList();
        // 3) smooth speed transitions: insert ramp halves between direction changes
        for (int i = 0; i < merged.Count; i++)
        {
            var cur = merged[i];
            if (i > 0)
            {
                var prev = merged[i - 1];
                bool flipL = Math.Sign(prev.L) != Math.Sign(cur.L) && prev.L != 0 && cur.L != 0;
                bool flipR = Math.Sign(prev.R) != Math.Sign(cur.R) && prev.R != 0 && cur.R != 0;
                if (flipL || flipR)
                    outPlan.Steps.Add(new PathStep(cur.L * 0.4, cur.R * 0.4, 0.12)); // gentle transition
            }
            outPlan.Steps.Add(cur);
        }
        return outPlan;
    }
}
