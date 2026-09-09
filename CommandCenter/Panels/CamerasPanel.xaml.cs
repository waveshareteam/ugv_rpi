using System.Windows;
using System.Windows.Controls;
using CommandCenter.Core;

namespace CommandCenter.Panels;

public partial class CamerasPanel : UserControl
{
    RobotClient _robot = null!;
    MjpegStreamer? _viewB;

    public CamerasPanel() => InitializeComponent();

    public void Init(RobotClient robot)
    {
        _robot = robot;
        robot.VideoFrame += f => Dispatcher.Invoke(() => ViewA.Source = f);
        robot.CamerasChanged += () => Dispatcher.Invoke(() =>
        {
            CamList.ItemsSource = null;
            CamList.ItemsSource = robot.State.Cameras;
            var act = robot.State.Cameras.FirstOrDefault(c => c.InUse);
            CamStatus.Text = act != null ? $"ACTIVE: /dev/video{act.Index}" : "";
        });

        // second, independent MJPEG connection for VIEW B
        _viewB = new MjpegStreamer(robot.State.BaseUrl + "/video_feed2");
        _viewB.Frame += f => Dispatcher.Invoke(() => ViewB.Source = f);
        _viewB.Start();

        _ = robot.RefreshCamerasAsync();
    }

    async void OnSwitch(object sender, RoutedEventArgs e)
    {
        if (CamList.SelectedItem is not CameraInfo cam) { MessageBox.Show("Select a camera in the list first."); return; }
        try
        {
            CamStatus.Text = $"Switching to /dev/video{cam.Index}…";
            await _robot.SelectCameraAsync(cam.Index);
            await Task.Delay(2500);            // give the server time to re-probe
            await _robot.RefreshCamerasAsync();
            CamStatus.Text = $"Switched to /dev/video{cam.Index}";
        }
        catch (Exception ex) { CamStatus.Text = ""; MessageBox.Show($"Switch failed: {ex.Message}"); }
    }

    async void OnRetry(object sender, RoutedEventArgs e)
    {
        try { await _robot.RetryCameraAsync(); CamStatus.Text = "Re-detecting…"; await Task.Delay(2000); await _robot.RefreshCamerasAsync(); }
        catch (Exception ex) { MessageBox.Show($"Retry failed: {ex.Message}"); }
    }

    void OnRefresh(object sender, RoutedEventArgs e) => _ = _robot.RefreshCamerasAsync();
}
