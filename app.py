from machine import Pin, SPI
import time

# 74HC595 / 4-digit 7-segment display
MOSI = 11
SCK = 10
RCLK = 9

KILOBIT = 0xFE   # hour tens
HUNDREDS = 0xFD  # hour units (decimal point)
TENS = 0xFB      # minute tens
UNITS = 0xF7     # minute units
DOT = 0x80

SEG8Code = [
    0x3F, 0x06, 0x5B, 0x4F, 0x66,
    0x6D, 0x7D, 0x07, 0x7F, 0x6F
]

NTP_SYNC_INTERVAL = 6 * 60 * 60
DISPLAY_REFRESH_MS = 2


class LED_8SEG:
    def __init__(self):
        self.rclk = Pin(RCLK, Pin.OUT)
        self.rclk(1)
        self.spi = SPI(
            1, 10_000_000, polarity=0, phase=0,
            sck=Pin(SCK), mosi=Pin(MOSI), miso=None
        )

    def write_cmd(self, digit, segments):
        self.rclk(1)
        self.spi.write(bytearray([digit, segments]))
        self.rclk(0)
        time.sleep_ms(1)
        self.rclk(1)

    def show_time(self, hour, minute):
        self.write_cmd(KILOBIT, SEG8Code[hour // 10])
        self.write_cmd(HUNDREDS, SEG8Code[hour % 10] | DOT)
        self.write_cmd(TENS, SEG8Code[minute // 10])
        self.write_cmd(UNITS, SEG8Code[minute % 10])


def sync_time():
    """Set Pico RTC from NTP. RTC is kept in UTC."""
    import ntptime
    ntptime.host = "pool.ntp.org"
    ntptime.settime()
    print("NTP synchronized (UTC):", time.gmtime())


def days_in_month(year, month):
    if month == 2:
        leap = (year % 4 == 0 and
                (year % 100 != 0 or year % 400 == 0))
        return 29 if leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def slovakia_is_dst(utc):
    """EU daylight-saving rule; transitions occur at 01:00 UTC."""
    year, month, day, hour = utc[0], utc[1], utc[2], utc[3]

    if 4 <= month <= 9:
        return True
    if month < 3 or month > 10:
        return False

    last_day = days_in_month(year, month)
    weekday_today = utc[6]  # Monday=0 ... Sunday=6
    weekday_last = (weekday_today + last_day - day) % 7
    last_sunday = last_day - ((weekday_last + 1) % 7)

    if month == 3:
        return day > last_sunday or (day == last_sunday and hour >= 1)

    # October: DST ends on the last Sunday at 01:00 UTC.
    return day < last_sunday or (day == last_sunday and hour < 1)


def slovakia_time():
    utc = time.gmtime()
    offset = 2 if slovakia_is_dst(utc) else 1
    seconds = time.mktime(utc) + offset * 3600
    return time.localtime(seconds)


def run():
    print("7-segment clock starting")
    display = LED_8SEG()

    try:
        sync_time()
    except Exception as exc:
        print("Initial NTP sync failed:", exc)

    last_sync = time.ticks_ms()
    last_shown_minute = -1

    while True:
        now = slovakia_time()
        minute_key = now[3] * 60 + now[4]

        if minute_key != last_shown_minute:
            print("Time: %02d.%02d" % (now[3], now[4]))
            last_shown_minute = minute_key

        # Keep multiplexing the display continuously.
        display.show_time(now[3], now[4])

        if time.ticks_diff(time.ticks_ms(), last_sync) >= NTP_SYNC_INTERVAL * 1000:
            try:
                sync_time()
            except Exception as exc:
                print("NTP resync failed:", exc)
            last_sync = time.ticks_ms()
            last_shown_minute = -1

        time.sleep_ms(DISPLAY_REFRESH_MS)
