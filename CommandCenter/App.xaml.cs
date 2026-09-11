using System.Windows;

namespace CommandCenter;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // surface any crash instead of dying silently
        DispatcherUnhandledException += (_, args) =>
        {
            MessageBox.Show(args.Exception.ToString(), "Command Center error",
                MessageBoxButton.OK, MessageBoxImage.Error);
            args.Handled = true;
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            MessageBox.Show(args.ExceptionObject?.ToString() ?? "unknown error",
                "Command Center fatal error", MessageBoxButton.OK, MessageBoxImage.Error);
        };
    }
}
