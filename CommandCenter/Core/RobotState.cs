namespace CommandCenter.Core;

/// <summary>Shared, change-notifying state of the robot as seen by the UI.</summary>
public class RobotState : System.ComponentModel.INotifyPropertyChanged
{
    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    void Raise(string n) => PropertyChanged?.Invoke(this, new(n));

    string _baseUrl = "http://172.30.136.241:5000";
    public string BaseUrl
    {
        get => _baseUrl;
        set { _baseUrl = value.TrimEnd('/'); HostLabel = new Uri(_baseUrl).Host; Raise(nameof(BaseUrl)); }
    }

    string _hostLabel = "172.30.136.241";
    public string HostLabel { get => _hostLabel; private set { _hostLabel = value; Raise(nameof(HostLabel)); } }

    // ── connection ──
    bool _connected;
    public bool Connected { get => _connected; set { _connected = value; Raise(nameof(Connected)); Raise(nameof(ConnText)); Raise(nameof(ConnBrush)); } }
    public string ConnText => Connected ? "● CONNECTED" : "○ OFFLINE";
    public System.Windows.Media.Brush ConnBrush => Connected
        ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4F, 0xF5, 0xC0))
        : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xFF, 0x93, 0x93));

    // ── config (fetched from /config) ──
    public double MaxSpeed = 0.5;
    public double SlowSpeed = 0.2;
    public int CmdMotion = 1;
    public int CmdGimbal = 133;
    public int CmdLightsHead = 10410;
    public int CmdLightsBase = 10411;
    public int CmdLightsAuto = 10405;
    public int CmdCvNone = 10301;
    public int CmdCvFace = 10303;
    public int CmdCvObjects = 10304;
    public int CmdCvColor = 10305;
    public int CmdCvMotion = 10302;
    public int CmdCvTrack = 10307;

    // ── live telemetry ──
    double _cpu, _ram, _volt, _rssi, _temp;
    public double Cpu  { get => _cpu;  set { _cpu = value;  Raise(nameof(CpuText)); } }
    public double Ram  { get => _ram;  set { _ram = value;  Raise(nameof(RamText)); } }
    public double Volt { get => _volt; set { _volt = value; Raise(nameof(VoltText)); } }
    public double Rssi { get => _rssi; set { _rssi = value; Raise(nameof(RssiText)); } }
    public double Temp { get => _temp; set { _temp = value; Raise(nameof(TempText)); } }
    public string CpuText  => $"CPU {Cpu,5:0.0}%   RAM {Ram,5:0.0}%";
    public string RamText  => $"RAM {Ram,5:0.0}%";
    public string VoltText => $"BAT {Volt,5:0.00}V  T {Temp,4:0.0}℃";
    public string TempText => $"TEMP {Temp,4:0.0}℃";
    public string RssiText => $"RSSI {Rssi,5:0} dBm";

    // ── drive ──
    double _speedScale = 1.0;
    public double SpeedScale { get => _speedScale; set { _speedScale = Math.Clamp(value, 0.1, 1.0); Raise(nameof(SpeedScale)); Raise(nameof(SpeedText)); } }
    public string SpeedText => $"Speed {SpeedScale * 100:0}%";
    bool _lightsOn;
    public bool LightsOn { get => _lightsOn; set { _lightsOn = value; Raise(nameof(LightsOn)); Raise(nameof(LightsText)); } }
    public string LightsText => LightsOn ? "💡 Lights ON" : "💡 Lights OFF";

    // ── lidar ──
    bool _avoidActive;
    public bool AvoidActive { get => _avoidActive; set { _avoidActive = value; Raise(nameof(AvoidActive)); Raise(nameof(AvoidText)); Raise(nameof(AvoidBrush)); } }
    public string AvoidText => AvoidActive ? "Avoidance: ACTIVE" : "Avoidance: PAUSED";
    public System.Windows.Media.Brush AvoidBrush => AvoidActive
        ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4F, 0xF5, 0xC0))
        : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF5, 0xBD, 0x5F));
    public System.Collections.Generic.List<(double AngleRad, double DistMm)> LidarScan = new();
    public double LidarMinM = double.MaxValue, LidarNearestDeg = 0;
    public string LidarSummary = "no data";
    bool _lidarHw;
    public bool LidarHw { get => _lidarHw; set { _lidarHw = value; Raise(nameof(LidarHwText)); } }
    bool _lidarStreaming;
    public bool LidarStreaming
    {
        get => _lidarStreaming;
        set { _lidarStreaming = value; Raise(nameof(LidarHwText)); Raise(nameof(LidarHwBrush)); }
    }
    public string LidarHwText =>
        LidarStreaming ? "LIDAR: streaming" :
        LidarHw ? "LIDAR: port open, no data (check power/cable)" :
        "LIDAR: not connected";
    public System.Windows.Media.Brush LidarHwBrush => LidarStreaming
        ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4F, 0xF5, 0xC0))
        : System.Windows.Media.Brushes.Orange;

    // ── cameras ──
    public System.Collections.Generic.List<CameraInfo> Cameras = new();
    public int ActiveCamera = -1;
    int _selectedCam;
    public int SelectedCam { get => _selectedCam; set { _selectedCam = value; Raise(nameof(SelectedCam)); } }

    // ── learning ──
    public string LearnStatus = "idle";
    public void Note(string msg) => LearnStatus = msg;
}
