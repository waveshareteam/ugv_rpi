using System;
using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CommandCenter.Core;

namespace CommandCenter.Panels;

public partial class ChatPanel : UserControl
{
    sealed record Message(string Name, string Text, string Color);

    RobotClient? _robot;
    readonly ObservableCollection<Message> _messages = new();
    bool _busy;

    public ChatPanel()
    {
        InitializeComponent();
        Log.ItemsSource = _messages;
        Append("Lance", "Bello! I'm Lance, the robot's brain. Ask me to do things — e.g. \"battery?\", \"lights on\", \"drive forward for two seconds\", \"take a photo\", \"what's nearest?\"");
    }

    public void Init(RobotClient robot)
    {
        _robot = robot;
        SendBtn.IsEnabled = true;
    }

    void Append(string name, string text)
    {
        _messages.Add(new Message(name, text, name == "You" ? "#FF8AB4F8" : "#FF4FF5C0"));
        Scroller.ScrollToEnd();
    }

    void OnInputFocus(object sender, RoutedEventArgs e) => Scroller.ScrollToEnd();

    void OnInputKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !_busy && _robot != null) Send();
    }

    void OnSend(object sender, RoutedEventArgs e) => Send();

    async void Send()
    {
        if (_busy || _robot == null) return;
        var q = InputBox.Text.Trim();
        if (q.Length == 0) return;

        _busy = true;
        SendBtn.IsEnabled = false;
        InputBox.Clear();
        Append("You", q);
        Append("Lance", "…");

        try
        {
            var reply = await _robot.LanceAsync(q);
            _messages.RemoveAt(_messages.Count - 1);   // drop the "…" row
            Append("Lance", string.IsNullOrWhiteSpace(reply) ? "(no reply)" : reply);
        }
        catch (Exception ex)
        {
            _messages.RemoveAt(_messages.Count - 1);
            Append("Lance", $"⚠ couldn't reach Lance: {ex.Message}");
        }
        finally
        {
            _busy = false;
            SendBtn.IsEnabled = true;
            InputBox.Focus();
        }
    }
}