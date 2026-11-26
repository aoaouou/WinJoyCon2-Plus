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
    /// <summary>由 Program 注入：收到震动包时怎么发布（side, 左右两个 4 字节块）。</summary>
    public static Action<string, byte[], byte[]>? OnRumbleBlocks;

    /// <summary>当前 hook 绑定的设备侧别（"L"/"R"）。</summary>
    public static string Side = "";

    /// <summary>OutputReceived 的事件处理体。</summary>
    public static void Handle(object? sender, object packet)
    {
        var blocks = DecodeRumbleBlocks(packet);
        if (blocks == null) return;
        try { OnRumbleBlocks?.Invoke(Side, blocks[0], blocks[1]); } catch { }
    }

    /// <summary>
    /// 从 HMOutputPacket 取出真机 JC1 的两个 4 字节震动块（左/右）。
    /// 不是震动包返回 null。
    ///
    /// ★ 不在 C# 里解振幅：旧 USB/IP 方案 rumble_hd.jc1_block_to_jc2 有
    ///   完整、经验证的解码链（SDL 权威振幅表 _HFA_KEYS、中性判定、
    ///   频率锁 JC2 原生）。这里只负责把**原始 4 字节块**送到 Python，
    ///   避免自己乱解（之前按 0x10 布局硬解 0x01 包 → 晃手柄就乱震）。
    ///
    /// 布局（ReportId 已被 SDK 提走，Data 从 ucPacketNumber 起）：
    ///   b[0]      = packetNumber
    ///   b[1..5]   = rumbleData[0]（4 字节，从 b[1] 起）
    ///   b[5..9]   = rumbleData[1]
    /// 而旧方案约定用 data[2:6] / data[6:10]（即含 packetNumber 的偏移），
    /// 两者等价：这里给 b[1:5] / b[5:9]。
    /// </summary>
    public static byte[][]? DecodeRumbleBlocks(object packet)
    {
        if (packet == null) return null;
        var t = packet.GetType();

        var ridF = t.GetField("ReportId");
        var dataF = t.GetField("Data");
        if (ridF == null || dataF == null) return null;

        byte rid = (byte)ridF.GetValue(packet)!;

        var srcF = t.GetField("Source");
        if (srcF != null)
        {
            var sv = srcF.GetValue(packet);
            if (sv != null && Convert.ToInt32(sv) != 0) return null;
        }

        // 只有 0x01（震动+子命令）和 0x10（纯震动）带震动块。
        if (rid != 0x01 && rid != 0x10) return null;

        var rom = (ReadOnlyMemory<byte>)dataF.GetValue(packet)!;
        var b = rom.ToArray();
        if (b.Length < 9) return null;

        var left = new byte[4];
        var right = new byte[4];
        Array.Copy(b, 1, left, 0, 4);
        Array.Copy(b, 5, right, 0, 4);
        return new[] { left, right };
    }
}
