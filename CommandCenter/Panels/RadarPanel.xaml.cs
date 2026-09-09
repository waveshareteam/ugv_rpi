using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using System.Windows.Threading;
using CommandCenter.Core;

namespace CommandCenter.Panels;

public partial class RadarPanel : UserControl
{
    RobotClient _robot = null!;
    DispatcherTimer? _render;

    public RadarPanel()
    {
        InitializeComponent();
        SizeChanged += (_, _) => Draw();
    }

    public void Init(RobotClient robot)
    {
        _robot = robot;
        DataContext = robot.State;
        robot.State.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(RobotState.AvoidActive) or nameof(RobotState.LidarHw))
                Dispatcher.Invoke(UpdateStatusLabels);
        };

        _render = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        _render.Tick += (_, _) => Draw();
        _render.Start();
        UpdateStatusLabels();
    }

    void UpdateStatusLabels()
    {
        var s = _robot.State;
        AvoidState.Text = s.AvoidText;
        AvoidState.Foreground = s.AvoidBrush;
        AvoidBtn.Content = s.AvoidActive ? "Disable Avoidance" : "Enable Avoidance";
        HwState.Text = s.LidarHwText;
        HwState.Foreground = s.LidarHw ? Brushes.MediumSpringGreen : Brushes.Orange;
    }

    async void OnAvoidToggle(object sender, RoutedEventArgs e)
    {
        try
        {
            bool target = !_robot.State.AvoidActive;
            await _robot.SetAvoidanceAsync(target);
            _robot.State.AvoidActive = target;
            UpdateStatusLabels();
        }
        catch (Exception ex) { MessageBox.Show($"Avoidance toggle failed: {ex.Message}"); }
    }

    void Draw()
    {
        var s = _robot.State;
        double w = RadarCanvas.ActualWidth, h = RadarCanvas.ActualHeight;
        if (w < 50 || h < 50) return;
        RadarCanvas.Children.Clear();

        double rangeM = RangeSlider.Value;
        double cx = w / 2, cy = h * 0.94;
        double maxR = Math.Min(w / 2, h * 0.94) - 8;
        double Scale(double meters) => meters / rangeM * maxR;

        static StreamGeometry Ring(double cx, double cy, double r)
        {
            var g = new StreamGeometry();
            using (var ctx = g.Open())
            {
                ctx.BeginFigure(new Point(cx - r, cy), false, false);
                ctx.ArcTo(new Point(cx + r, cy), new Size(r, r), 0, false, SweepDirection.Counterclockwise, true, false);
            }
            g.Freeze();
            return g;
        }

        // range rings + labels
        for (int i = 1; i <= 3; i++)
        {
            double r = maxR * i / 3;
            var ring = new Path { Data = Ring(cx, cy, r), Stroke = new SolidColorBrush(Color.FromArgb(70, 0x4F, 0xF5, 0xC0)), StrokeThickness = 1, StrokeDashArray = new DoubleCollection { 4, 3 } };
            RadarCanvas.Children.Add(ring);
            var lbl = new TextBlock { Text = $"{rangeM * i / 3:0.#}m", Foreground = new SolidColorBrush(Color.FromArgb(140, 0x4F, 0xF5, 0xC0)), FontSize = 10 };
            Canvas.SetLeft(lbl, cx + 4); Canvas.SetTop(lbl, cy - r - 14);
            RadarCanvas.Children.Add(lbl);
        }

        // forward line
        RadarCanvas.Children.Add(new Line { X1 = cx, Y1 = cy, X2 = cx, Y2 = cy - maxR, Stroke = new SolidColorBrush(Color.FromArgb(110, 0x4F, 0xF5, 0xC0)), StrokeThickness = 1 });

        // avoidance keep-out wedge (±40°, 0.5 m)
        var wedge = new Path
        {
            Data = CreateWedge(cx, cy, Scale(0.5), -40, 40),
            Fill = new SolidColorBrush(Color.FromArgb(46, 0xFF, 0x93, 0x93))
        };
        RadarCanvas.Children.Add(wedge);

        // robot icon
        RadarCanvas.Children.Add(new Rectangle { Width = 22, Height = 14, Fill = Brushes.MediumSpringGreen, RadiusX = 3, RadiusY = 3, RenderTransform = new TranslateTransform(cx - 11, cy - 7) });

        // scan dots (web convention: lidar angle 0 = rear; rotate +180°, mirror so +angle = left)
        if (s.LidarScan.Count > 0)
        {
            double rangeMm = rangeM * 1000;
            var dots = new StreamGeometry();
            using (var ctx = dots.Open())
            {
                foreach (var (a, d) in s.LidarScan)
                {
                    if (d <= 0 || d > rangeMm) continue;
                    double ang = a + Math.PI;
                    double px = cx + Scale(d / 1000.0) * Math.Sin(ang);
                    double py = cy - Scale(d / 1000.0) * Math.Cos(ang);
                    ctx.BeginFigure(new Point(px, py), true, false);
                    ctx.LineTo(new Point(px + 1.6, py), true, false);
                    ctx.LineTo(new Point(px + 1.6, py + 1.6), true, false);
                    ctx.LineTo(new Point(px, py + 1.6), true, false);
                }
            }
            dots.Freeze();
            RadarCanvas.Children.Add(new Path { Data = dots, Fill = new SolidColorBrush(Color.FromArgb(220, 0xFF, 0x5A, 0x5A)) });
        }

        ScanInfo.Text = s.LidarSummary;
        NearestInfo.Text = s.LidarMinM > 0 ? $"Nearest: {s.LidarMinM:0.00} m @ {s.LidarNearestDeg:0}°" : "Nearest: —";

        static Geometry CreateWedge(double cx, double cy, double r, double a1, double a2)
        {
            var g = new StreamGeometry();
            double rad1 = a1 * Math.PI / 180, rad2 = a2 * Math.PI / 180;
            var p1 = new Point(cx + r * Math.Sin(rad1), cy - r * Math.Cos(rad1));
            var p2 = new Point(cx + r * Math.Sin(rad2), cy - r * Math.Cos(rad2));
            using (var ctx = g.Open())
            {
                ctx.BeginFigure(new Point(cx, cy), true, true);
                ctx.LineTo(p1, true, false);
                ctx.ArcTo(p2, new Size(r, r), 0, false, SweepDirection.Clockwise, true, false);
            }
            g.Freeze();
            return g;
        }
    }
}
