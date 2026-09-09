using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using CommandCenter.Core;

namespace CommandCenter.Panels;

public partial class DrivePanel : UserControl
{
    RobotClient _robot = null!;
    DispatcherTimer? _keyTimer;
    readonly System.Collections.Generic.HashSet<Key> _keys = new();
    string _padDir = "";          // current D-pad direction tag

    public DrivePanel()
    {
        InitializeComponent();
        IsVisibleChanged += (_, _) =>
        {
            if (IsVisible) Focus();
        };
    }

    public void Init(RobotClient robot)
    {
        _robot = robot;
        DataContext = robot.State;
        robot.VideoFrame += f => Dispatcher.Invoke(() => VideoImage.Source = f);

        SpeedSlider.ValueChanged += (_, _) =>
        {
            SpeedLabel.Text = $"{SpeedSlider.Value * 100:0}%";
            robot.State.SpeedScale = SpeedSlider.Value;
        };

        // label follows actual state (flipped only after the REST round-trip succeeds)
        robot.State.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(RobotState.LightsText))
                Dispatcher.Invoke(() => LightsBtn.Content = robot.State.LightsText);
        };

        // keyboard driving loop — sends a repeated hold frame while keys are down
        _keyTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        _keyTimer.Tick += (_, _) => SendKeyDrive();
        _keyTimer.Start();

        PreviewKeyDown += OnKey;
        PreviewKeyUp += OnKey;
        LostKeyboardFocus += (_, _) => { _keys.Clear(); SendKeyDrive(); };
    }

    void OnKey(object sender, KeyEventArgs e)
    {
        var k = e.Key == Key.System ? e.SystemKey : e.Key;
        if (k is Key.W or Key.A or Key.S or Key.D or Key.Q or Key.E or Key.Space or
            Key.Up or Key.Down or Key.Left or Key.Right)
        {
            if (e.IsRepeat) return;
            if (Keyboard.IsKeyDown(k)) _keys.Add(k); else _keys.Remove(k);
            if (k == Key.Space && Keyboard.IsKeyDown(k)) _robot.Stop();
            SendKeyDrive();
            e.Handled = true;
        }
    }

    void SendKeyDrive()
    {
        if (_padDir != "") return;                       // D-pad owns the robot while held
        double max = _robot.State.MaxSpeed * _robot.State.SpeedScale;
        bool w = _keys.Contains(Key.W), s = _keys.Contains(Key.S),
              a = _keys.Contains(Key.A), d = _keys.Contains(Key.D),
              q = _keys.Contains(Key.Q), e2 = _keys.Contains(Key.E);
        int fwd = (w ? 1 : 0) - (s ? 1 : 0);
        int turn = (d ? 1 : 0) - (a ? 1 : 0);
        int spin = (e2 ? 1 : 0) - (q ? 1 : 0);
        if (fwd == 0 && turn == 0 && spin == 0) { if (_robot.WasDriving) _robot.Stop(); return; }
        if (spin != 0) { _robot.Drive(spin * max, -spin * max); return; }
        double l = fwd * max, r = fwd * max;
        if (turn > 0) { l = fwd * max * 0.6; r = fwd * max; }
        if (turn < 0) { l = fwd * max; r = fwd * max * 0.6; }
        _robot.Drive(l, r);
        // arrow keys nudge the gimbal while driving
        if (_keys.Contains(Key.Left)) _robot.Gimbal(-12, 0);
        if (_keys.Contains(Key.Right)) _robot.Gimbal(12, 0);
        if (_keys.Contains(Key.Up)) _robot.Gimbal(0, -10);
        if (_keys.Contains(Key.Down)) _robot.Gimbal(0, 10);
    }

    // ── D-pad ──
    void OnDirHold(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Primitives.RepeatButton b) return;
        string dir = (string)b.Tag;
        if (_padDir == dir) return;
        _padDir = dir;
        double max = _robot.State.MaxSpeed * _robot.State.SpeedScale;
        double slow = max * 0.4;
        (double L, double R) v = dir switch
        {
            "fwd" => (max, max),
            "back" => (-max, -max),
            "fwd_left" => (slow, max),
            "fwd_right" => (max, slow),
            "back_left" => (-slow, -max),
            "back_right" => (-max, -slow),
            _ => (0, 0)
        };
        _robot.Drive(v.L, v.R);
    }

    void OnDirRelease(object sender, MouseEventArgs e)
    {
        if (_padDir == "") return;
        _padDir = "";
        _robot.Stop();
    }

    void OnStop(object sender, RoutedEventArgs e) { _padDir = ""; _robot.Stop(); }

    void OnSpeedChanged(object sender, RoutedEventArgs e) { }

    // ── buttons ──
    void OnLights(object sender, RoutedEventArgs e)
    {
        _robot.LightsToggle();          // REST /toggle_lights; label updates on success via PropertyChanged
    }

    async void OnAutoDrive(object sender, RoutedEventArgs e)
    {
        try
        {
            var r = await _robot.PostFormAsync("/execute_command",
                new() { ["command"] = _robot.State.AvoidActive ? "stop_auto_drive" : "start_auto_drive" });
            bool started = r.TryGetProperty("status", out var st) && st.GetString() == "success";
            if (started) _robot.State.AvoidActive = !_robot.State.AvoidActive;
            AutoBtn.Content = _robot.State.AvoidActive ? "🚗 Auto-Drive ON" : "🐢 Auto-Drive OFF";
        }
        catch (Exception ex) { MessageBox.Show($"Auto-drive failed: {ex.Message}"); }
    }

    async void OnSnapshot(object sender, RoutedEventArgs e)
    {
        try
        {
            var bytes = await _robot.SnapshotJpegAsync();
            string dir = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), "RobotCommandCenter");
            Directory.CreateDirectory(dir);
            string file = System.IO.Path.Combine(dir, $"snap_{DateTime.Now:yyyyMMdd_HHmmss}.jpg");
            await File.WriteAllBytesAsync(file, bytes);
            MessageBox.Show($"Saved: {file}", "Snapshot", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { MessageBox.Show($"Snapshot failed: {ex.Message}"); }
    }

    private void OnCv(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b) return;
        int code = (string)b.Tag switch
        {
            "face" => _robot.State.CmdCvFace,
            "objs" => _robot.State.CmdCvObjects,
            "color" => _robot.State.CmdCvColor,
            "motion" => _robot.State.CmdCvMotion,
            "track" => _robot.State.CmdCvTrack,
            _ => _robot.State.CmdCvNone
        };
        _robot.CvMode(code);
    }
}
