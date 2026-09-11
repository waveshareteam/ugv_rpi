using System.Windows;
using System.Windows.Controls;
using CommandCenter.Core;

namespace CommandCenter;

public partial class MainWindow : Window
{
    readonly RobotClient _robot = new();

    public MainWindow()
    {
        InitializeComponent();
        ConnText.DataContext = _robot.State;
        ConnText.SetBinding(TextBlock.TextProperty, new System.Windows.Data.Binding("ConnText"));
        ConnText.SetBinding(TextBlock.ForegroundProperty, new System.Windows.Data.Binding("ConnBrush"));

        DriveTab.Init(_robot);
        RadarTab.Init(_robot);
        CamerasTab.Init(_robot);
        LearningTab.Init(_robot);
        ChatTab.Init(_robot);

        _robot.State.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(RobotState.LidarHwText))
                Dispatcher.Invoke(() => LidarWarn.Text = _robot.State.LidarHw ? "" : "⚠ LIDAR silent — check sensor power/cable");
        };

        Closed += async (_, _) => { await _robot.DisposeAsync(); };
        ConnectBtn_Click(null, null);   // auto-connect to the remembered host
    }

    void OnConnect(object sender, RoutedEventArgs e) => ConnectBtn_Click(sender, e);

    void ConnectBtn_Click(object? sender, RoutedEventArgs? e)
    {
        var url = HostBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;
        _robot.Connect(url);
        ConnectBtn.Content = "Reconnect";
    }
}
