"""Pico W boot, bounded Wi-Fi update check, then local app.py.

OTA source: http://HOST/firmware/<DEVICE_ID>/manifest.json. Manifest format:
{"version":"1", "files":{"app.py":"<sha256>", "sim868.py":"<sha256>"}}
The bootloader main.py is never overwritten by OTA.
"""
import os
import time
import machine
import network
import ujson
import uhashlib
import ubinascii
import config

DEVICE_ID = "".join("{:02x}".format(b) for b in machine.unique_id())
BASE_URL = "http://" + config.HOST.rstrip("/") + "/firmware/" + DEVICE_ID + "/"
PROTECTED = ("main.py", "config.py", "boot.py")
MAX_FILE_BYTES = 70000

def sha256(data):
    return ubinascii.hexlify(uhashlib.sha256(data).digest()).decode()

def fetch(url):
    import urequests
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            raise OSError("HTTP status %s" % response.status_code)
        return response.content
    finally:
        response.close()

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    for attempt in range(2):
        try:
            wlan.connect(config.SSID, config.PASS)
            start = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), start) < 7000:
                if wlan.isconnected():
                    print("Wi-Fi connected:", wlan.ifconfig()[0])
                    return True
                time.sleep_ms(200)
        except Exception as exc:
            print("Wi-Fi error:", exc)
        try:
            wlan.disconnect()
        except Exception:
            pass
    print("Wi-Fi unavailable; local app will run")
    return False

def update_firmware():
    base = BASE_URL.rstrip("/")
    raw = fetch(base + "/manifest.json")
    if len(raw) > 10000:
        raise ValueError("manifest too large")
    manifest = ujson.loads(raw)
    version = str(manifest["version"])
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("invalid manifest")
    if len(files) > 12:
        raise ValueError("too many files")
    try:
        with open("version.txt", "r") as f:
            if f.read().strip() == version:
                print("Firmware current:", version)
                return
    except OSError:
        pass
    staged = []
    swapped = []
    backed_up = []
    try:
        for name, digest in files.items():
            if (not isinstance(name, str) or not name.endswith(".py")
                    or name.startswith(".") or "/" in name or "\\" in name
                    or name in PROTECTED or ".." in name):
                raise ValueError("disallowed firmware filename: %s" % name)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError("invalid SHA256 for %s" % name)
            data = fetch(base + "/" + name)
            if len(data) > MAX_FILE_BYTES or sha256(data) != digest.lower():
                raise ValueError("SHA256/size mismatch: %s" % name)
            tmp = name + ".new"
            with open(tmp, "wb") as f:
                f.write(data)
            staged.append(name)
        # Keep backups so failed swaps can be rolled back.
        for name in staged:
            try:
                os.remove(name + ".bak")
            except OSError:
                pass
            try:
                os.rename(name, name + ".bak")
                backed_up.append(name)
            except OSError:
                pass  # first install
            os.rename(name + ".new", name)
            swapped.append(name)
        with open("version.txt.new", "w") as f:
            f.write(version)
        os.rename("version.txt.new", "version.txt")
        print("Firmware updated to", version)
    except Exception:
        # Roll back all swapped files (including partial installs).
        for name in reversed(swapped):
            try:
                os.remove(name)
            except OSError:
                pass
        for name in reversed(backed_up):
            try:
                os.rename(name + ".bak", name)
            except OSError:
                pass
        for name in staged:
            try:
                os.remove(name + ".new")
            except OSError:
                pass
        raise

def boot():
    # Blink during boot, Wi-Fi check and OTA. app.py takes over LED control.
    led = machine.Pin("LED", machine.Pin.OUT)
    led_timer = machine.Timer(-1)
    led_timer.init(period=150, mode=machine.Timer.PERIODIC,
                   callback=lambda timer: led.toggle())
    # Give Thonny time to attach after Pico starts.
    print("Startup delay: 15 seconds (Thonny connection)")
    time.sleep(15)
    print("Pico DEVICE_ID:", DEVICE_ID)
    print("Firmware URL:", BASE_URL)
    if connect_wifi():
        try:
            update_firmware()
        except Exception as exc:
            print("OTA skipped:", exc)
    led_timer.deinit()
    led.value(0)
    import app
    app.run()

try:
    boot()
except Exception as exc:
    import sys
    sys.print_exception(exc)
    time.sleep(5)
    machine.reset()
