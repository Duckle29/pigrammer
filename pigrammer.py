#!/usr/bin/python3
import subprocess
import time
import wiringpi as wp
import signal
import sys
from os import execl
import logging
from systemd.journal import JournaldLogHandler

from git import Repo
import requests

import Adafruit_GPIO.SPI as SPI
import Adafruit_SSD1306
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

avrdude_path = '/usr/bin/avrdude'
mcu = 'm32u4'
avrdude_timeout = 20  # Timeout in seconds before killing avrdude
bootloader_hex = '/home/pi/pigrammer/hexes/vitamins_included_rev2_default_production.hex'
low_fuse = '0xDE'
high_fuse = '0x98'
ext_fuse = '0xCB'
log_file = '/home/pi/log'

debounce_time = 0.05  # Time spent ignoring more button pushes

# Pins
pin_button = 22     # Pin 15
pin_led_good = 27   # Pin 11
pin_led_bad = 17    # Pin 13
pin_oled_rst = 23   # Pin 16

shutdown_delay = 6  # Time in seconds to hold programming button for to shut down


def cleanup():
	wp.pullUpDnControl(pin_button, wp.PUD_OFF)
	wp.pinMode(pin_led_good, wp.INPUT)
	wp.pinMode(pin_led_good, wp.INPUT)
	wp.pinMode(pin_led_bad, wp.INPUT)
	wp.pinMode(pin_oled_rst, wp.INPUT)


def shutdown():
	global lines
	global main_draw
	main_draw = False
	time.sleep(0.5)
	lines = ["Shutting down", "wait for green", "led to stop", "Then turn off"]
	drawScreen(x, image, lines)

	command = ["/usr/bin/sudo", "/sbin/shutdown","-h","0"]
	process = subprocess.Popen(command, stdout=subprocess.PIPE)
	sys.exit(0)


def drawScreen(x, image, lines):
	# Draw a black filled box to clear the image.
	lines = lines[-4:]
	draw.rectangle((0,0,width,height), outline=0, fill=0)

	for idx, line in enumerate(lines):
		draw.text((x+1,top+((font_size+5)*idx)), line, font=font, fill=255)

	disp.image(image)
	disp.display()


def flash(avrdude_path,hex_path,log_file,ext_fuse,high_fuse,low_fuse,timeout):
	global main_draw
	global x
	global image
	main_draw = False

	command_fuses = [
		avrdude_path,
		"-p", mcu,
		"-c", "linuxspi",
		"-P", "/dev/spidev0.0",
		"-b", "250000",
		"-e",
		"-U", "lfuse:w:{}:m".format(low_fuse),
		"-U", "hfuse:w:{}:m".format(high_fuse),
		"-U", "efuse:w:{}:m".format(ext_fuse)
	]

	command_flash = [
		avrdude_path,
		"-p", mcu,
		"-c", "linuxspi",
		"-P", "/dev/spidev0.0",
		"-b", "4000000",
		"-U", "flash:w:{}".format(hex_path),
	]

	lines = ['Flashing']
	drawScreen(x, image, lines)
	lines = []

	P_flash = subprocess.Popen(command_fuses, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

	while True:
		termline = P_flash.stdout.readline().decode()

		if termline == '' and P_flash.poll() is not None:
			break
		else:
			if "1 bytes of efuse verified" in termline:
				lines.append("EFUSE OK")
				logger.info("EFUSE : OK")
				drawScreen(x, image, lines)
			elif "1 bytes of hfuse verified" in termline:
				lines.append("HFUSE OK")
				logger.info("HFUSE : OK")
				drawScreen(x, image, lines)
			elif "1 bytes of lfuse verified" in termline:
				lines.append("LFUSE OK")
				logger.info("LFUSE : OK")
				drawScreen(x, image, lines)
			elif "error" in termline or "override" in termline:
				main_draw = True
				raise SystemError(termline)

	P_flash = subprocess.Popen(command_flash, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

	while True:
		termline = P_flash.stdout.readline().decode()

		if termline == '' and P_flash.poll() is not None:
			break
		else:
			if "bytes of flash verified" in termline:
				lines.append("FLASH OK")
				logger.info("FLASH : OK")
				drawScreen(x, image, lines)
			elif "error" in termline:
				main_draw = True
				raise SystemError(termline)

	main_draw = True


def signal_handler(sig, frame):
	print("Exiting program")
	logger.info("Exiting program")
	cleanup()
	sys.exit(0)


def debounce_handler():
	global last_push

	if not wp.digitalRead(pin_button):
		if time.time() - last_push > debounce_time:
			last_push = time.time()
			flash_handler()


def flash_handler():

	global lines
	global main_draw
	global x
	global image
	lines = []

	start = time.time()
	last_disp_time = 0
	while not wp.digitalRead(pin_button):
		main_draw = False
		countdown = int(time.time() - start)
		if last_disp_time != countdown:
			lines = ["Shutting down in", "{}".format(shutdown_delay - countdown)]
			last_disp_time = countdown
			drawScreen(x, image, lines)
		if time.time() - start > shutdown_delay:
			print("Shutting down")
			logger.info("Shutting down")
			cleanup()
			shutdown()
	main_draw = True

	print("Trying to flash")

	try:
		wp.digitalWrite(pin_led_good, wp.LOW)
		wp.digitalWrite(pin_led_bad, wp.LOW)
		start = time.time() # Time used to timeout avrdude
		logger.info("Flashing started at: {}".format(start))
		flash(avrdude_path, bootloader_hex,log_file,ext_fuse,high_fuse,low_fuse, avrdude_timeout)
	except SystemError as e:
		# Log
		logger.error("Error flashing: {}".format(e))

		# Print info
		print("Error flashing: {}".format(e))

		# Display info
		lines = []
		lines.append("Error flashing")
		lines.append("Try again")
		wp.digitalWrite(pin_led_good, wp.LOW)
		wp.digitalWrite(pin_led_bad, wp.HIGH)
	else:
		logger.info("Chip flashed in: {} seconds".format(time.time()-start))
		wp.digitalWrite(pin_led_good, wp.HIGH)
		wp.digitalWrite(pin_led_bad, wp.LOW)
		lines = ["Ready to flash"]


def is_online():
	req = requests.get('http://clients3.google.com/generate_204')
	if req.status_code == 204:
		return True
	else:
		return False


def update():
	global x
	global image
	repo = Repo('/home/pi/pigrammer')
	repo.remotes.origin.fetch()
	commits_behind = sum(1 for c in (repo.iter_commits('production..production@{u}')))
	if commits_behind > 0:
		lines = ['Updating']
		logger.info('Update available, updating')
		drawScreen(x, image, lines)

		repo.remotes.origin.pull()

		lines = ["Updated", "restarting"]
		drawScreen(x, image, lines)
		time.sleep(1)
		cleanup()
		python = sys.executable
		execl(python, python, *sys.argv)

	lines = ["Up to date"]
	logger.info('Up to date')
	drawScreen(x, image, lines)
	time.sleep(1)


## Setup
wp.wiringPiSetupGpio()

wp.pinMode(pin_button, wp.INPUT)
wp.pullUpDnControl(pin_button, wp.PUD_UP)

wp.pinMode(pin_led_bad, wp.OUTPUT)
wp.pinMode(pin_led_good, wp.OUTPUT)
wp.pinMode(pin_oled_rst, wp.OUTPUT)

wp.digitalWrite(pin_led_good, wp.HIGH)
wp.digitalWrite(pin_led_bad, wp.LOW)

disp = Adafruit_SSD1306.SSD1306_128_64(rst=pin_oled_rst, i2c_address=0x3C)
disp.begin()

last_push = 0

# Loggin related setup
logger = logging.getLogger('PiGrammer')
journald_handler = JournaldLogHandler()

# set a formatter to include the level name
journald_handler.setFormatter(logging.Formatter(
	'[%(levelname)s] %(message)s'
))

# add the journald handler to the current logger
logger.addHandler(journald_handler)

# optionally set the logging level
logger.setLevel(logging.INFO)

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
padding = 0
top = padding
bottom = height-padding
# Move left to right keeping track of the current x position for drawing shapes.
x = 0

font_size = 11
font = ImageFont.truetype('8-bit-fortress.ttf', font_size)

#### End of display stuff

main_draw = True

if is_online():
	logger.info('Pigrammer is online, checking for updates')
	lines = ['Checking for', 'updates']
	drawScreen(x, image, lines)
	time.sleep(1)
	update()

signal.signal(signal.SIGINT, signal_handler)
wp.wiringPiISR(pin_button, wp.INT_EDGE_FALLING, debounce_handler)

print("Startig PiGrammer")
logger.info("Starting PiGrammer")

lines = ["Ready to flash"]
while True:
	if main_draw:
		drawScreen(x, image, lines)
		time.sleep(0.5)
