// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// Mynaphone per-process audio capture helper.
//
// Captures the audio rendered by one process (and optionally its child processes) using the
// Windows process-loopback API (ActivateAudioInterfaceAsync + AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)
// and writes raw interleaved 32-bit float PCM to stdout. Status lines go to stderr:
//   READY rate=48000 channels=2
//   FLAGS <n>            a packet carried AUDCLNT_BUFFERFLAGS_* bits (1 = data discontinuity)
//   EXIT <reason>
//
// Usage: mynaphone-capture.exe --pid <n> [--exclude-tree] [--rate 48000] [--channels 2]
// Compiles with the C# 5 compiler that ships with Windows (.NET Framework 4.x csc.exe).

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace Mynaphone
{
    [StructLayout(LayoutKind.Sequential)]
    struct WAVEFORMATEX
    {
        public ushort wFormatTag;
        public ushort nChannels;
        public uint nSamplesPerSec;
        public uint nAvgBytesPerSec;
        public ushort nBlockAlign;
        public ushort wBitsPerSample;
        public ushort cbSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS
    {
        public uint TargetProcessId;
        public int ProcessLoopbackMode;   // 0 = include target process tree, 1 = exclude
    }

    [StructLayout(LayoutKind.Sequential)]
    struct AUDIOCLIENT_ACTIVATION_PARAMS
    {
        public int ActivationType;        // 1 = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
        public AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS ProcessLoopbackParams;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct BLOB
    {
        public uint cbSize;
        public IntPtr pBlobData;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct PROPVARIANT_BLOB
    {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public BLOB blob;
    }

    [ComImport, Guid("72A22D78-CDE4-431D-B8CC-843A71199B6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceAsyncOperation
    {
        void GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
    }

    [ComImport, Guid("41D949AB-9862-444A-80F6-C261334DA5EB"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceCompletionHandler
    {
        void ActivateCompleted(IActivateAudioInterfaceAsyncOperation activateOperation);
    }

    [ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioClient
    {
        int Initialize(int shareMode, uint streamFlags, long hnsBufferDuration, long hnsPeriodicity, ref WAVEFORMATEX pFormat, IntPtr audioSessionGuid);
        int GetBufferSize(out uint numBufferFrames);
        int GetStreamLatency(out long hnsLatency);
        int GetCurrentPadding(out uint numPaddingFrames);
        int IsFormatSupported(int shareMode, ref WAVEFORMATEX pFormat, out IntPtr closestMatch);
        int GetMixFormat(out IntPtr deviceFormat);
        int GetDevicePeriod(out long hnsDefaultDevicePeriod, out long hnsMinimumDevicePeriod);
        int Start();
        int Stop();
        int Reset();
        int SetEventHandle(IntPtr eventHandle);
        int GetService(ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppv);
    }

    [ComImport, Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioCaptureClient
    {
        int GetBuffer(out IntPtr data, out uint numFramesToRead, out uint flags, out ulong devicePosition, out ulong qpcPosition);
        int ReleaseBuffer(uint numFramesRead);
        int GetNextPacketSize(out uint numFramesInNextPacket);
    }

    // Marker interface: declares the handler apartment-agnostic. Without it the activation call
    // fails with E_ILLEGAL_METHOD_CALL.
    [ComImport, Guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAgileObject
    {
    }

    [ComVisible(true)]
    class CompletionHandler : IActivateAudioInterfaceCompletionHandler, IAgileObject
    {
        public ManualResetEvent Done = new ManualResetEvent(false);
        public int Hr = 0;
        public object Client = null;

        public void ActivateCompleted(IActivateAudioInterfaceAsyncOperation op)
        {
            try
            {
                int hr;
                object iface;
                op.GetActivateResult(out hr, out iface);
                Hr = hr;
                Client = iface;
            }
            catch (Exception e)
            {
                Hr = e.HResult;
            }
            Done.Set();
        }
    }

    static class Native
    {
        [DllImport("Mmdevapi.dll", CharSet = CharSet.Unicode, ExactSpelling = true, PreserveSig = false)]
        public static extern void ActivateAudioInterfaceAsync(
            [MarshalAs(UnmanagedType.LPWStr)] string deviceInterfacePath,
            ref Guid riid,
            IntPtr activationParams,
            IActivateAudioInterfaceCompletionHandler completionHandler,
            out IActivateAudioInterfaceAsyncOperation activationOperation);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr CreateEvent(IntPtr lpEventAttributes, bool bManualReset, bool bInitialState, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr hObject);

        [DllImport("avrt.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr AvSetMmThreadCharacteristics(string taskName, ref uint taskIndex);
    }

    static class Program
    {
        const string VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback";
        const uint AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000;
        const uint AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000;
        const uint AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000;
        const uint AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000;
        const ushort WAVE_FORMAT_IEEE_FLOAT = 3;
        const ushort VT_BLOB = 0x41;

        [MTAThread]
        static int Main(string[] args)
        {
            uint pid = 0;
            int mode = 0;          // include tree
            uint rate = 48000;
            ushort channels = 2;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--pid" && i + 1 < args.Length) pid = uint.Parse(args[++i]);
                else if (args[i] == "--exclude-tree") mode = 1;
                else if (args[i] == "--rate" && i + 1 < args.Length) rate = uint.Parse(args[++i]);
                else if (args[i] == "--channels" && i + 1 < args.Length) channels = ushort.Parse(args[++i]);
            }
            if (pid == 0 && mode == 0)
            {
                Console.Error.WriteLine("EXIT usage: --pid <n> [--exclude-tree] [--rate 48000] [--channels 2]");
                return 2;
            }
            try
            {
                return Run(pid, mode, rate, channels);
            }
            catch (Exception e)
            {
                Console.Error.WriteLine("EXIT error " + e.GetType().Name + ": " + e.Message + " hr=0x" + e.HResult.ToString("X8"));
                return 1;
            }
        }

        static int Run(uint pid, int mode, uint rate, ushort channels)
        {
            // activation parameters -> PROPVARIANT(VT_BLOB)
            var p = new AUDIOCLIENT_ACTIVATION_PARAMS();
            p.ActivationType = 1;
            p.ProcessLoopbackParams.TargetProcessId = pid;
            p.ProcessLoopbackParams.ProcessLoopbackMode = mode;
            int psize = Marshal.SizeOf(typeof(AUDIOCLIENT_ACTIVATION_PARAMS));
            IntPtr pMem = Marshal.AllocHGlobal(psize);
            Marshal.StructureToPtr(p, pMem, false);
            var pv = new PROPVARIANT_BLOB();
            pv.vt = VT_BLOB;
            pv.blob.cbSize = (uint)psize;
            pv.blob.pBlobData = pMem;
            int pvsize = Marshal.SizeOf(typeof(PROPVARIANT_BLOB));
            IntPtr pvMem = Marshal.AllocHGlobal(Math.Max(pvsize, 24));
            Marshal.StructureToPtr(pv, pvMem, false);

            var handler = new CompletionHandler();
            Guid iidAudioClient = new Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2");
            IActivateAudioInterfaceAsyncOperation op;
            Native.ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, ref iidAudioClient, pvMem, handler, out op);
            if (!handler.Done.WaitOne(5000))
            {
                Console.Error.WriteLine("EXIT activation timed out");
                return 3;
            }
            if (handler.Hr < 0 || handler.Client == null)
            {
                Console.Error.WriteLine("EXIT activation failed hr=0x" + handler.Hr.ToString("X8"));
                return 4;
            }
            var client = (IAudioClient)handler.Client;

            var fmt = new WAVEFORMATEX();
            fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
            fmt.nChannels = channels;
            fmt.nSamplesPerSec = rate;
            fmt.wBitsPerSample = 32;
            fmt.nBlockAlign = (ushort)(channels * 4);
            fmt.nAvgBytesPerSec = rate * fmt.nBlockAlign;
            fmt.cbSize = 0;

            uint flags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                       | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
            long bufferDuration = 10000000;   // 1 s in 100-ns units
            int hr = client.Initialize(0, flags, bufferDuration, 0, ref fmt, IntPtr.Zero);
            if (hr < 0)
            {
                Console.Error.WriteLine("EXIT Initialize failed hr=0x" + hr.ToString("X8"));
                return 5;
            }

            IntPtr evt = Native.CreateEvent(IntPtr.Zero, false, false, null);
            hr = client.SetEventHandle(evt);
            if (hr < 0)
            {
                Console.Error.WriteLine("EXIT SetEventHandle failed hr=0x" + hr.ToString("X8"));
                return 6;
            }
            Guid iidCapture = new Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317");
            object svc;
            hr = client.GetService(ref iidCapture, out svc);
            if (hr < 0)
            {
                Console.Error.WriteLine("EXIT GetService failed hr=0x" + hr.ToString("X8"));
                return 7;
            }
            var capture = (IAudioCaptureClient)svc;

            uint taskIndex = 0;
            Native.AvSetMmThreadCharacteristics("Pro Audio", ref taskIndex);

            hr = client.Start();
            if (hr < 0)
            {
                Console.Error.WriteLine("EXIT Start failed hr=0x" + hr.ToString("X8"));
                return 8;
            }
            Console.Error.WriteLine("READY rate=" + rate + " channels=" + channels + " pid=" + pid);
            Console.Error.Flush();

            Stream stdout = Console.OpenStandardOutput();
            byte[] buf = new byte[fmt.nBlockAlign * 4096];
            bool parentGone = false;
            var watchdog = new Thread(() =>
            {
                // stop when stdin closes (the parent went away)
                try { while (Console.In.Read() != -1) { } } catch { }
                parentGone = true;
            });
            watchdog.IsBackground = true;
            watchdog.Start();

            while (!parentGone)
            {
                uint w = Native.WaitForSingleObject(evt, 2000);
                uint packet;
                while (capture.GetNextPacketSize(out packet) >= 0 && packet > 0)
                {
                    IntPtr data; uint frames; uint pflags; ulong devPos; ulong qpc;
                    hr = capture.GetBuffer(out data, out frames, out pflags, out devPos, out qpc);
                    if (hr < 0)
                    {
                        Console.Error.WriteLine("EXIT GetBuffer failed hr=0x" + hr.ToString("X8"));
                        return 9;
                    }
                    int bytes = (int)(frames * fmt.nBlockAlign);
                    if (bytes > buf.Length) buf = new byte[bytes];
                    if ((pflags & 2) != 0)             // AUDCLNT_BUFFERFLAGS_SILENT
                        Array.Clear(buf, 0, bytes);
                    else
                        Marshal.Copy(data, buf, 0, bytes);
                    if ((pflags & ~2u) != 0)
                    {
                        Console.Error.WriteLine("FLAGS " + pflags);
                        Console.Error.Flush();
                    }
                    try { stdout.Write(buf, 0, bytes); }
                    catch (IOException) { parentGone = true; break; }
                    capture.ReleaseBuffer(frames);
                }
                if (w == 0xFFFFFFFF) break;
            }
            try { stdout.Flush(); } catch { }
            client.Stop();
            Native.CloseHandle(evt);
            Console.Error.WriteLine("EXIT done");
            return 0;
        }
    }
}
