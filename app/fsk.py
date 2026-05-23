import numpy as np

FSK_SAMPLE_RATE = 48000
FSK_BAUD_RATE = 1200
FSK_MARK_FREQ = 1200
FSK_SPACE_FREQ = 2200
FSK_SAMPLES_PER_BIT = FSK_SAMPLE_RATE // FSK_BAUD_RATE
FSK_PREAMBLE_BITS = 24  # require 24 consecutive mark bits (~20ms) to sync
FSK_EOM_BITS = 8  # 8 consecutive mark bits after data = end of message


def goertzel(samples: np.ndarray, freq: float, sample_rate: int) -> float:
    n = len(samples)
    k = freq * n / sample_rate
    omega = 2.0 * np.pi * k / n
    coef = 2.0 * np.cos(omega)
    s1, s2 = 0.0, 0.0
    for x in samples:
        s0 = x + coef * s1 - s2
        s2 = s1
        s1 = s0
    return s2 * s2 + s1 * s1 - coef * s1 * s2


def is_mark(window: np.ndarray) -> bool:
    return goertzel(window, FSK_MARK_FREQ, FSK_SAMPLE_RATE) > goertzel(window, FSK_SPACE_FREQ, FSK_SAMPLE_RATE) * 1.5


class FskDecoder:
    def __init__(self) -> None:
        self.buf = np.array([], dtype=np.float32)
        self.synced = False
        self.mark_cnt = 0  # consecutive mark bits seen
        self.eom_cnt = 0  # consecutive mark bits seen after data started
        self.message = b""

    def feed(self, samples: np.ndarray) -> bytes | None:
        self.buf = np.concatenate([self.buf, samples])
        result = None

        while len(self.buf) >= FSK_SAMPLES_PER_BIT:
            window = self.buf[:FSK_SAMPLES_PER_BIT]
            mark = is_mark(window)

            if not self.synced:
                if mark:
                    self.mark_cnt += 1
                    self.buf = self.buf[FSK_SAMPLES_PER_BIT:]
                    if self.mark_cnt >= FSK_PREAMBLE_BITS:
                        self.synced = True
                        self.mark_cnt = 0
                        self.eom_cnt = 0
                        self.message = b""
                else:
                    # not mark — slide one sample to find preamble edge
                    self.mark_cnt = 0
                    self.buf = self.buf[1:]
            else:
                # synced: expect start bit (space) or EOM (mark)
                if mark:
                    self.eom_cnt += 1
                    self.buf = self.buf[FSK_SAMPLES_PER_BIT:]
                    if self.eom_cnt >= FSK_EOM_BITS and self.message:
                        # end of message
                        result = self.message
                        self.synced = False
                        self.mark_cnt = 0
                        self.eom_cnt = 0
                        self.message = b""
                    continue

                # space = start bit, read 8 data bits + stop bit
                needed = FSK_SAMPLES_PER_BIT * 10
                if len(self.buf) < needed:
                    break

                self.eom_cnt = 0
                byte_val = 0
                for b in range(8):
                    offset = (b + 1) * FSK_SAMPLES_PER_BIT
                    bit_window = self.buf[offset : offset + FSK_SAMPLES_PER_BIT]
                    if is_mark(bit_window):
                        byte_val |= 1 << b

                self.message += bytes([byte_val])
                self.buf = self.buf[needed:]

        return result
