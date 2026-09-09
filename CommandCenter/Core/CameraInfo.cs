namespace CommandCenter.Core;

public class CameraInfo
{
    public int Index { get; set; }          // /dev/videoN index
    public string Name { get; set; } = "?";
    public bool InUse { get; set; }
    public override string ToString() => $"/dev/video{Index} — {Name}{(InUse ? "  [ACTIVE]" : "")}";
}
