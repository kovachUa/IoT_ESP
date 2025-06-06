import time

class BH1750:
    PWR_ON = 0x01
    RESET = 0x07
    CONT_H_RES_MODE = 0x10

    def __init__(self, i2c, addr=0x23):
        self.i2c = i2c
        self.addr = addr
        self.i2c.writeto(self.addr, bytearray([self.PWR_ON]))
        time.sleep(0.01)
        self.i2c.writeto(self.addr, bytearray([self.RESET]))
        time.sleep(0.01)

    def luminance(self):
        self.i2c.writeto(self.addr, bytearray([self.CONT_H_RES_MODE]))
        time.sleep(0.2)
        data = self.i2c.readfrom(self.addr, 2)
        return (data[0] << 8 | data[1]) / 1.2  # lux