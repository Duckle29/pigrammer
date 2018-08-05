#!/usr/bin/python3

avrdude_path    = '/usr/bin/avrdude'
avrdude_timeout = 100 # Timeout in seconds before killing avrdude
bootloader_hex  = '/home/pi/hexes/vitamins_included_rev2_default_production.hex'
low_fuse        = '0x5E'
high_fuse       = '0xD9'
ext_fuse        = '0xC3'
lock_fuse       = '0x3F'
log_file        = '/home/pi/log'

# Pins
pin_button      = 22 # Pin 15
pin_led_good    = 17 # Pin 11
pin_led_bad     = 27 # Pin 13
pin_oled_rst    = 23 # Pin 16


import subprocess
import time
import RPi.GPIO as GPIO
import signal
import sys

import Adafruit_GPIO.SPI as SPI
import Adafruit_SSD1306
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

# Setup
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(pin_led_bad, GPIO.OUT)
GPIO.setup(pin_led_good, GPIO.OUT)
GPIO.setup(pin_oled_rst, GPIO.OUT)

disp = Adafruit_SSD1306.SSD1306_128_64(rst=pin_oled_rst, i2c_address=0x3C)
disp.begin()

state = 0

#### Display stuff

# Clear display.
disp.clear()
disp.display()

# Create blank image for drawing.
# Make sure to create image with mode '1' for 1-bit color.
width = disp.width
height = disp.height
image = Image.new('1', (width, height))

# Get drawing object to draw on image.
draw = ImageDraw.Draw(image)

# Draw a black filled box to clear the image.
draw.rectangle((0,0,width,height), outline=0, fill=0)

# Draw some shapes.
# First define some constants to allow easy resizing of shapes.
padding = -2
top = padding
bottom = height-padding
# Move left to right keeping track of the current x position for drawing shapes.
x = 0

# Load default font.
font = ImageFont.truetype('VCR_OSD_MONO_1.001.ttf',10)

#### End of display stuff

def restart():
    command = ["/usr/bin/sudo",  "/sbin/reboot"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    output = process.communicate()[0]
    print(output)

def shutdown():
    command = ["/usr/bin/sudo", "/sbin/shutdown -h 0"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    output = process.communicate()[0]
    print(output)

def drawScreen(x, image, lines):
    # Draw a black filled box to clear the image.
    draw.rectangle((0,0,width,height), outline=0, fill=0)
    
    for idx, line in enumerate(lines):
        draw.text((x,top+(8*idx)), line, font=font, fill=255)
    
    disp.image(image)
    disp.display()



def flash(avrdude_path, hex_path,log_file,ext_fuse,high_fuse,low_fuse,lock_fuse, timeout):
    
    command = "{} -p m32u4 -c linuxspi -P /dev/spidev0.0 -b 4000000 -U flash:w:{}:a -U lfuse:w:{}:m -U hfuse:w:{}:m -U efuse:w:{}:m -U lock:w:{}:m &>{}".format(avrdude_path, hex_path, low_fuse, high_fuse, ext_fuse, lock_fuse, log_file)

    command = [avrdude_path, 
    "-p", "m32u4",
    "-c", "linuxspi",
    "-P", "/dev/spidev0.0",
    "-b", "4000000",
    "-U", "flash:w:{}".format(hex_path),
    "-U", "lfuse:w:{}:m".format(low_fuse),
    "-U", "hfuse:w:{}:m".format(high_fuse),
    "-U", "efuse:w:{}:m".format(ext_fuse),
    "-U", "lock:w:{}:m".format(lock_fuse)
    ]

    lines = []

    start = time.time() # Time used to timeout avrdude
    P_flash = subprocess.Popen(command, stdout=subprocess.PIPE)

    while P_flash.poll == None:
        
        if time.time() - start > timeout:
            P_flash.kill()
            raise SystemError("AVRDUDE timed out")

        for line in P_flash.stdout:
            if "1 bytes of efuse verified" in line:
                lines.append("EFUSE : OK")
                print("EFUSE : OK")
            elif "1 bytes of hfuse verified" in line:
                lines.append("HFUSE : OK")
                print("HFUSE : OK")
            elif "1 bytes of lfuse verified" in line:
                lines.append("LFUSE : OK")
                print("LFUSE : OK")
            elif "error" in line:
                lines.append("ERROR")
                print("ERROR flashing: {}").format(line)
                raise SystemError("Error flashing: {}".format(line))
            #print("Debug: {}".format(line))
        
        drawScreen(x, image, lines)
        time.sleep(0.1)

def signal_handler(sig, frame):
	print("Exiting program")
	GPIO.cleanup()
	sys.exit(0)

def flash_handler(channel):
	print("Trying to flash")
        try:
            flash(avrdude_path, bootloader_hex,log_file,ext_fuse,high_fuse,low_fuse,lock_fuse, avrdude_timeout):
        except SystemError as e:
            print("Error flashing: {}".format(e))
            lines = []
            lines.append("Error flashing board", "Try again")
            GPIO.output(pin_led_good, GPIO.LOW)
            GPIO.output(pin_led_bad, GPIO.HIGH)
		else:
			GPIO.output(pin_led_good, GPIO.HIGH)
        	GPIO.output(pin_led_bad, GPIO.LOW)
			lines = ["Ready to flash", "Place probe on board", "Push button to flash"]

signal.signal(signal.SIGINT, signal_handler)
GPIO.add_event_detect(pin_button, GPIO.FALLING, callback=flash_handler, bouncetime=10)

print("Startig loop")
 
while True:
    drawScreen(x, image, lines)
    time.sleep(0.5)