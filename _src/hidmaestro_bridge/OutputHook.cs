using System;
using System.Reflection;

namespace HmBridgeSupport;

/// <summary>
/// Output 报告解码辅助。
///
/// 为什么单独一个文件：Program.cs 是 C# 顶级语句（没有类包裹），
/// 无法用 typeof(Program) 取到静态方法给 Expression 生成委托。
/// 放在这里就能被 typeof(OutputHook) 引用。
///
/// 背景：HIDMaestro 的 OutputDecoded（profile decoder 路径）在 usbip
/// 后端实测不触发；改用 OutputReceived(Action&lt;HMController,HMOutputPacket&gt;)
/// 拿原始字节，按真机 JC1 的 wire 格式自己解振幅。
/// </summary>
public static class OutputHook
{
    /// <summary>由 Program 注入：收到震动包时怎么发布（side, amp）。</summary>
    public static Action<string, float>? OnRumble;

    /// <summary>当前 hook 绑定的设备侧别（"L"/"R"）。</summary>
    public static string Side = "";

    /// <summary>
    /// OutputReceived 的事件处理体。签名刻意用 (object, object)，配合
    /// Program 侧的 open-instance 委托绑定，避免顶级语句里拿不到类型。
    /// </summary>
    public static void Handle(object? sender, object packet)
    {
        float amp = DecodeAmplitude(packet);
        if (amp < 0f) return;
        try { OnRumble?.Invoke(Side, amp); } catch { }
    }

    /// <summary>
    /// 从 HMOutputPacket（反射传入）解出震动振幅 0..1。
    /// 不是震动包（report id 不是 0x01/0x10、或 source 不是 HidOutput）返回 -1。
    /// </summary>
    public static float DecodeAmplitude(object packet)
    {
        if (packet == null) return -1f;
        var t = packet.GetType();

        var ridF = t.GetField("ReportId");
        var dataF = t.GetField("Data");
        if (ridF == null || dataF == null) return -1f;

        byte rid = (byte)ridF.GetValue(packet)!;

        // Source：0 = HidOutput（0x01 带子命令 / 0x10 纯震动）。
        // 其它（HidFeature / XInput…）不是我们要的震动包。
        var srcF = t.GetField("Source");
        if (srcF != null)
        {
            var sv = srcF.GetValue(packet);
            if (sv != null && Convert.ToInt32(sv) != 0) return -1f;
        }

        if (rid != 0x01 && rid != 0x10) return -1f;

        var rom = (ReadOnlyMemory<byte>)dataF.GetValue(packet)!;
        var b = rom.ToArray();
        // SDL SwitchCommonOutputPacket_t（ReportId 已被 SDK 提走）：
        //   b[0]      = packetNumber
        //   b[1..4]   = rumbleData[0]：HFfreq, HFamp|freq高位, LFfreq|amp高位, LFamp
        //   b[5..8]   = rumbleData[1]
        // HF 振幅 4 bit（/15）；LF 振幅 9 bit（b[3] 的 bit7 是最高位，/511）
        if (b.Length < 9) return -1f;

        int hf = b[2] & 0x0F;
        int lf = ((b[3] & 0x80) << 1) | b[4];
        return Math.Max(hf / 15f, lf / 511f);
    }
}
