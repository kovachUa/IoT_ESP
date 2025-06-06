from framebuf import FrameBuffer, MONO_VLSB

class SH1106:
    def __init__(self, width, height, i2c, addr=0x3C):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.pages = self.height // 8
        self.buffer = bytearray(self.width * self.pages)
        self.framebuf = FrameBuffer(self.buffer, self.width, self.height, MONO_VLSB)
        self.init_display()

    def write_cmd(self, cmd):
        self.i2c.writeto(self.addr, bytearray([0x00, cmd]))

    def write_data(self, buf):
        self.i2c.writeto(self.addr, bytearray([0x40]) + buf)

    def init_display(self):
        for cmd in (
            0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00,
            0x40, 0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12,
            0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4,
            0xA6, 0xAF
        ):
            self.write_cmd(cmd)
        self.fill(0) # Use the modified fill method which calls framebuf.fill()
        self.show()

    def fill(self, color):
        # self.buffer will be filled by framebuf operations
        self.framebuf.fill(color)

    def pixel(self, x, y, color):
        self.framebuf.pixel(x, y, color)

    def text(self, string, x, y, color=1):
        self.framebuf.text(string, x, y, color)

    def show(self):
        for page in range(self.pages):
            self.write_cmd(0xB0 + page)
            self.write_cmd(0x02) # Column start address (lower nibble, 0 an 1 set for SH1106)
            self.write_cmd(0x10) # Column start address (higher nibble)
            start_index = self.width * page
            end_index = start_index + self.width
            self.write_data(self.buffer[start_index:end_index])