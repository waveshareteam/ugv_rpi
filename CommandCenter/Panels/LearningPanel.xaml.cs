using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using CommandCenter.Core;
using CommandCenter.Learning;

namespace CommandCenter.Panels;

public partial class LearningPanel : UserControl
{
    RobotClient _robot = null!;
    AutoPilot _pilot = null!;
    readonly ObstacleMemory _memory = new();
    readonly ColorBlobTracker _tracker = new();
    DateTime _lastFeed = DateTime.MinValue;

    // recording state
    bool _recording;
    double _recL, _recR;
    DateTime _recStepStart;
    readonly List<PathPlan.PathStep> _recorded = new();

    DispatcherTimer? _ui;

    public LearningPanel() => InitializeComponent();

    public void Init(RobotClient robot)
    {
        _robot = robot;
        _pilot = new AutoPilot(
            (l, r) => Task.Run(() => _robot.Drive(l, r)),
            () => _robot.State.LidarScan.Select(t => (t.AngleRad, t.DistMm)).ToArray(),
            () => _tracker.LatestBoxes,
            _memory);

        // feed the color-blob tracker from the live video (throttled inside)
        _robot.VideoFrame += f =>
        {
            if ((DateTime.UtcNow - _lastFeed).TotalMilliseconds > 100)
            {
                _lastFeed = DateTime.UtcNow;
                Task.Run(() => _tracker.Feed(f));
            }
        };

        _ui = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(160) };
        _ui.Tick += (_, _) =>
        {
            DrawMemory();
            DecisionText.Text = _pilot.LastDecision;
            FollowBtn.Content = _pilot.CurrentMode == AutoPilot.Mode.FollowObject ? "🎯 Engaged…" : "🎯 Engage";
            GoBtn.Content = _pilot.CurrentMode == AutoPilot.Mode.Reactive ? "🧠 Engaged…" : "🧠 Engage";
            TrackerInfo.Text = _tracker.LatestBoxes.Length > 0
                ? $"target locked ({_tracker.LastBlobPixels} px blob)"
                : $"searching hue {HueSlider.Value:0}°…";
        };

        HueSlider.ValueChanged += (_, _) =>
        {
            var c = HsvToRgb(HueSlider.Value, 1, 1);
            ((SolidColorBrush)HuePreview.Fill).Color = Color.FromRgb(c.r, c.g, c.b);
            _tracker.TargetHue = HueSlider.Value;
        };
        _ui.Start();

        LoadPathList();
    }

    // ───────── recording ─────────
    void OnRecord(object sender, RoutedEventArgs e)
    {
        if (!_recording)
        {
            _recorded.Clear();
            _recL = _recR = 0; _recStepStart = DateTime.UtcNow;
            _recording = true;
            RecBtn.Content = "⏹ Stop Recording";
            RecInfo.Text = "recording… drive the robot";
            _robot.CommandSent += OnCmdForRecording;
            StepList.ItemsSource = null;
        }
        else
        {
            _recording = false;
            _robot.CommandSent -= OnCmdForRecording;
            FlushStep(force: true);
            RecBtn.Content = "⏺ Start Recording";
            RecInfo.Text = $"{_recorded.Count} steps captured — refine & save";
            RenderSteps();
        }
    }

    void OnCmdForRecording(double l, double r)
    {
        if (!_recording) return;
        if (Math.Abs(l - _recL) > 0.02 || Math.Abs(r - _recR) > 0.02)
        {
            FlushStep();
            _recL = l; _recR = r;
            _recStepStart = DateTime.UtcNow;
        }
    }

    void FlushStep(bool force = false)
    {
        double secs = (DateTime.UtcNow - _recStepStart).TotalSeconds;
        if (force || secs > 0.05) _recorded.Add(new PathPlan.PathStep(_recL, _recR, Math.Max(0.05, secs)));
    }

    void RenderSteps()
    {
        StepList.ItemsSource = _recorded
            .Select((s, i) => $"{i,3}: L {s.L:+0.00;-0.00}  R {s.R:+0.00;-0.00}  {s.Seconds,5:0.00}s")
            .ToList();
    }

    void OnSave(object sender, RoutedEventArgs e)
    {
        if (_recorded.Count == 0) { MessageBox.Show("Nothing recorded yet."); return; }
        FlushStep(force: true);
        var raw = new PathPlan { Name = $"teach_{DateTime.Now:HHmmss}", Steps = _recorded.ToList() };
        var refined = raw.Refined();
        raw.Save(); refined.Save();
        LoadPathList();
        RecInfo.Text = $"saved: {raw.Name} ({raw.Steps.Count} steps) + refined ({refined.Steps.Count} steps)";
        _recorded.Clear();
        RenderSteps();
    }

    void LoadPathList()
    {
        var items = PathPlan.Saved().Select(p => System.IO.Path.GetFileName(p.name)).ToList();
        PathBox.ItemsSource = items;
        if (items.Count > 0) PathBox.SelectedIndex = 0;
    }

    // ───────── autopilot modes ─────────
    void OnReplay(object sender, RoutedEventArgs e)
    {
        if (PathBox.SelectedItem is not string name) { MessageBox.Show("Pick a saved path first."); return; }
        var file = PathPlan.Saved().First(p => p.name == name + ".json").file;
        var plan = PathPlan.Load(file);
        if (plan == null) return;
        if (name.EndsWith("_refined")) plan = plan; // already refined
        _pilot.CruiseSpeed = CruiseSlider.Value;
        _pilot.DangerM = DangerSlider.Value;
        _pilot.Start(AutoPilot.Mode.Replay, plan);
        DecisionText.Text = "replay started";
    }

    void OnReactive(object sender, RoutedEventArgs e)
    {
        _pilot.CruiseSpeed = CruiseSlider.Value;
        _pilot.DangerM = DangerSlider.Value;
        _pilot.GoalHeadingDeg = GoalSlider.Value;
        _pilot.Start(AutoPilot.Mode.Reactive);
        DecisionText.Text = "reactive autopilot engaged";
    }

    void OnFollow(object sender, RoutedEventArgs e)
    {
        _tracker.TargetHue = HueSlider.Value;
        _tracker.Enabled = true;
        _pilot.Start(AutoPilot.Mode.FollowObject);
        DecisionText.Text = $"follow-object engaged (hue {HueSlider.Value:0}°)";
    }

    void OnStopAuto(object sender, RoutedEventArgs e)
    {
        _pilot.Stop();
        DecisionText.Text = "stopped — robot parked";
    }

    static (byte r, byte g, byte b) HsvToRgb(double h, double s, double v)
    {
        double c = v * s, x = c * (1 - Math.Abs(h / 60.0 % 2 - 1)), m = v - c;
        double rr, gg, bb;
        if (h < 60) { rr = c; gg = x; bb = 0; }
        else if (h < 120) { rr = x; gg = c; bb = 0; }
        else if (h < 180) { rr = 0; gg = c; bb = x; }
        else if (h < 240) { rr = 0; gg = x; bb = c; }
        else if (h < 300) { rr = x; gg = 0; bb = c; }
        else { rr = c; gg = 0; bb = x; }
        return ((byte)((rr + m) * 255), (byte)((gg + m) * 255), (byte)((bb + m) * 255));
    }

    // ───────── memory map ─────────
    void DrawMemory()
    {
        double w = MemCanvas.ActualWidth, h = MemCanvas.ActualHeight;
        if (w < 40 || h < 40) return;
        MemCanvas.Children.Clear();
        double scale = Math.Min(w, h) / (ObstacleMemory.Size * ObstacleMemory.CellM) * 0.95;

        foreach (var (mx, my, hits) in _memory.Cells(minHits: 2))
        {
            byte a = (byte)Math.Min(230, 60 + hits * 18);
            var cell = new Rectangle
            {
                Width = scale * ObstacleMemory.CellM + 1,
                Height = scale * ObstacleMemory.CellM + 1,
                Fill = new SolidColorBrush(Color.FromArgb(a, 0xFF, 0x5A, 0x5A))
            };
            Canvas.SetLeft(cell, w / 2 + mx * scale);
            Canvas.SetTop(cell, h / 2 - my * scale);
            MemCanvas.Children.Add(cell);
        }

        // goal heading arrow
        double goal = GoalSlider.Value * Math.PI / 180;
        MemCanvas.Children.Add(new Line
        {
            X1 = w / 2, Y1 = h / 2,
            X2 = w / 2 + 40 * Math.Sin(goal), Y2 = h / 2 - 40 * Math.Cos(goal),
            Stroke = Brushes.MediumSpringGreen, StrokeThickness = 2, StrokeDashArray = new DoubleCollection { 3, 2 }
        });

        MemInfo.Text = $"{_memory.BusyCells} cells learned · {_robot.State.LidarSummary}";
    }
}
