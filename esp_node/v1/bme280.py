import time
import struct

class BME280:
    def __init__(self, i2c, address=0x76):
        self.i2c = i2c
        self.addr = address
        self._load_calibration()
        self.i2c.writeto_mem(self.addr, 0xF2, b'\x01')  # humidity oversampling x1
        self.i2c.writeto_mem(self.addr, 0xF4, b'\x27')  # normal mode, temp/press oversampling x1

    def _read16(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        return struct.unpack('<H', data)[0]

    def _readS16(self, reg):
        val = self._read16(reg)
        return val - 65536 if val > 32767 else val

    def _load_calibration(self):
        self.dig_T1 = self._read16(0x88)
        self.dig_T2 = self._readS16(0x8A)
        self.dig_T3 = self._readS16(0x8C)
        self.dig_P1 = self._read16(0x8E)
        self.dig_P2 = self._readS16(0x90)
        self.dig_P3 = self._readS16(0x92)
        self.dig_P4 = self._readS16(0x94)
        self.dig_P5 = self._readS16(0x96)
        self.dig_P6 = self._readS16(0x98)
        self.dig_P7 = self._readS16(0x9A)
        self.dig_P8 = self._readS16(0x9C)
        self.dig_P9 = self._readS16(0x9E)
        self.dig_H1 = self.i2c.readfrom_mem(self.addr, 0xA1, 1)[0]
        h = self.i2c.readfrom_mem(self.addr, 0xE1, 7)
        self.dig_H2 = struct.unpack('<h', h[0:2])[0]
        self.dig_H3 = h[2]
        e4 = h[3]
        e5 = h[4]
        e6 = h[5]
        self.dig_H4 = (e4 << 4) | (e5 & 0x0F)
        self.dig_H5 = (e6 << 4) | (e5 >> 4)
        self.dig_H6 = struct.unpack('b', bytes([h[6]]))[0]

    def read_raw_data(self):
        data = self.i2c.readfrom_mem(self.addr, 0xF7, 8)
        adc_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        adc_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        adc_h = (data[6] << 8) | data[7]
        return adc_t, adc_p, adc_h

    def compensate_temperature(self, adc_t):
        var1 = (adc_t / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        var2 = ((adc_t / 131072.0 - self.dig_T1 / 8192.0) ** 2) * self.dig_T3
        self.t_fine = var1 + var2
        return self.t_fine / 5120.0

    def compensate_pressure(self, adc_p):
        var1 = self.t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.dig_P6 / 32768.0
        var2 = var2 + var1 * self.dig_P5 * 2.0
        var2 = var2 / 4.0 + self.dig_P4 * 65536.0
        var1 = (self.dig_P3 * var1 * var1 / 524288.0 + self.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.dig_P1
        if var1 == 0:
            return 0
        p = 1048576.0 - adc_p
        p = ((p - var2 / 4096.0) * 6250.0) / var1
        var1 = self.dig_P9 * p * p / 2147483648.0
        var2 = p * self.dig_P8 / 32768.0
        return p + (var1 + var2 + self.dig_P7) / 16.0

    def compensate_humidity(self, adc_h):
        h = self.t_fine - 76800.0
        h = (adc_h - (self.dig_H4 * 64.0 + self.dig_H5 / 16384.0 * h)) * \
            (self.dig_H2 / 65536.0 * (1.0 + self.dig_H6 / 67108864.0 * h *
            (1.0 + self.dig_H3 / 67108864.0 * h)))
        h = h * (1.0 - self.dig_H1 * h / 524288.0)
        return max(0.0, min(h, 100.0))

    def read_compensated_data(self):
        adc_t, adc_p, adc_h = self.read_raw_data()
        temperature = self.compensate_temperature(adc_t)
        pressure = self.compensate_pressure(adc_p) / 100  # в гПа
        humidity = self.compensate_humidity(adc_h)
        return temperature, pressure, humidity