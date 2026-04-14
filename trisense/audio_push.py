"""Trimite PCM stereo catre ESP32 pentru redare I2S."""

from __future__ import annotations

import logging
import socket
import struct

logger = logging.getLogger(__name__)

_MAGIC = b"TPCM"
# Lower streaming bandwidth for smoother playback on ESP over Wi-Fi.
_TARGET_SAMPLE_RATE = 16000
# Tuning for small 4 ohm / 2W speaker: less bass + safer level.
_OUT_GAIN_Q15 = 21000
_HP_ALPHA_Q15 = 29491  # ~0.9 (simple high-pass / DC-block)


def send_pcm_to_esp(host: str, port: int, pcm: bytes, sample_rate: int) -> bool:
    """Protocol simplu: TPCM + rate_u32 + len_u32 + payload PCM16 stereo."""
    if not host or not pcm:
        return False
    if sample_rate < 8000 or sample_rate > 48000:
        sample_rate = 24000
    if len(pcm) < 2:
        return False
    pcm, sample_rate = _resample_mono_pcm16(pcm, sample_rate, _TARGET_SAMPLE_RATE)
    pcm_out = _mono_to_stereo_pcm16(pcm, gain_q15=24500)
    if not pcm_out:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(12.0)
        sock.connect((host, int(port)))
        header = _MAGIC + struct.pack("<II", int(sample_rate), int(len(pcm_out)))
        sock.sendall(header)
        sock.sendall(pcm_out)
        logger.info("Audio TCP trimis la %s:%s (%d B @ %d Hz)", host, port, len(pcm_out), sample_rate)
        return True
    except Exception as e:
        logger.warning("Audio TCP esuat catre %s:%s: %s", host, port, e)
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _mono_to_stereo_pcm16(pcm_mono: bytes, gain_q15: int = _OUT_GAIN_Q15) -> bytes:
    """Mono PCM16 -> stereo PCM16 (L=R), with light high-pass + fixed gain."""
    if len(pcm_mono) < 2:
        return b""
    if len(pcm_mono) % 2:
        pcm_mono = pcm_mono[:-1]
    out = bytearray((len(pcm_mono) // 2) * 4)
    o = 0
    prev_x = 0
    prev_y = 0
    for i in range(0, len(pcm_mono), 2):
        s = struct.unpack_from("<h", pcm_mono, i)[0]
        # y[n] = x[n] - x[n-1] + a*y[n-1] (removes rumble / resonance load)
        y = s - prev_x + ((prev_y * _HP_ALPHA_Q15) >> 15)
        prev_x = s
        prev_y = y
        s = (y * gain_q15) >> 15
        if s > 32767:
            s = 32767
        if s < -32768:
            s = -32768
        struct.pack_into("<hh", out, o, s, s)
        o += 4
    return bytes(out)


def _resample_mono_pcm16(pcm_mono: bytes, src_rate: int, dst_rate: int) -> tuple[bytes, int]:
    """Very light nearest-neighbor resample on PC side."""
    if len(pcm_mono) < 4 or src_rate == dst_rate:
        return pcm_mono, src_rate
    if len(pcm_mono) % 2:
        pcm_mono = pcm_mono[:-1]
    src_samples = len(pcm_mono) // 2
    if src_samples < 2:
        return pcm_mono, src_rate
    out_samples = (src_samples * dst_rate) // src_rate
    if out_samples < 2:
        return pcm_mono, src_rate
    out = bytearray(out_samples * 2)
    # Fixed-point index mapping, no heavy math.
    for i in range(out_samples):
        src_i = (i * src_rate) // dst_rate
        if src_i >= src_samples:
            src_i = src_samples - 1
        s = struct.unpack_from("<h", pcm_mono, src_i * 2)[0]
        struct.pack_into("<h", out, i * 2, s)
    return bytes(out), dst_rate
