# Raspberry Pi Pico
# -*- coding: utf-8 -*-
#
#**************************************************************************
#
#   Copyright (c) 2023 by Petri Damstén <petri.damsten@iki.fi>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the
#   Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
#**************************************************************************

import board
import busio
import displayio
import socketpool
import wifi
import rtc
import os
import time
import ssl
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text import label
import adafruit_requests
import adafruit_ntp
from adafruit_st7735r import ST7735R
from adafruit_datetime import datetime, timedelta
import adafruit_imageload

def main():
    global display, lblTime, lblDate, lblTemp

    connectWifi()
    initDisplay()
    initWidgets()

    pdate = datetime.now() - timedelta(days = 1, minutes = 1, hours = 1)
    while True:
        d = datetime.now()
        if pdate.day != d.day:
            try:
                daily()
            except Exception as e:
                print("daily failed", str(e))
        if pdate.hour != d.hour:
            try:
                hourly()
            except Exception as e:
                print("hourly failed", str(e))
        if pdate.minute != d.minute:
            try:
                minutes()
            except Exception as e:
                print("minutes failed", str(e))
        pdate = d
        sleep()

def guard(tid, atleastsec):
    global TICK, ticks
    if tid in ticks:
        if atleastsec > (ticks['current'] - ticks[tid]) * TICK:
            return False
    ticks[tid] = ticks['current']
    return True
    
def sleep():
    global TICK, ticks
    ticks['current'] += 1
    time.sleep(TICK)

def daily():
    print('Updating date & ntp')
    if guard('time', 3600):
        updateTime()
    print('**', datetime.now())
    lblDate.text = formatDate()

def hourly():
    if guard('temp', 1800):
        print('Updating temperature')
        temp = getTemp()
        print('**', temp)
        lblTemp.text = formatTemp(temp)
        lblTemp.color = 0x88BBFF if temp < 0 else 0xFF6B0D

def minutes():
    print('Updating time')
    lblTime.text = formatTime()

def isEUDst(date):
    dtstart = datetime(date.year, 3, 31, 3, 00)
    dtend = datetime(date.year, 10, 31, 3, 00)
    dtstart -= timedelta(days = (dtstart.weekday() + 1) % 7)
    dtend -= timedelta(days = (dtend.weekday() + 1) % 7)
    return 1 if (date > dtstart and date < dtend) else 0

def formatTemp(temp):
    return f'{int(abs(round(temp, 0))):0=2}'

def formatTime():
    date = datetime.now()
    return f'{(date.hour + isEUDst(date)):0=2}:{date.minute:0=2}'

def formatDate():
    date = datetime.now()
    return f'{date.day:0=2}.{date.month:0=2}.{str(date.year)[-2:]}'

def connectWifi():    
    if DEBUG:
        return
    try:
        wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
    except Exception as e:
        print('Wifi failed', str(e))

def getTemp():
    if DEBUG:
        return 0.0
    lat = os.getenv("WEATHER_LATITUDE") 
    lon = os.getenv("WEATHER_LONGITUDE")
    url = 'https://api.open-meteo.com/v1/forecast?latitude=' + lat + '&longitude=' + lon + \
          '&current=temperature_2m'
    data = getJson(url)
    return data['current']['temperature_2m']

def getJson(url):
    data = {}
    try:
        pool = socketpool.SocketPool(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl.create_default_context())
        response = requests.get(url)
        data = response.json()
        response.close()
    except Exception as e:
        print("json failed", str(e))
    return data

def initDisplay():
    global display
    displayio.release_displays()
    spi = busio.SPI(clock = SCK, MOSI = SDA)
    dbus = displayio.FourWire(spi, command = AO, chip_select = CS, reset = RESET)
    display = ST7735R(dbus, width = 160, height = 128, rotation = 90, bgr = True)

def addImage(group, bitmap):
    bmp = displayio.TileGrid(bitmap, pixel_shader = bitmap.pixel_shader)
    group.append(bmp)
    return bmp

def addTextOld(group, txt, font, x, y, color = 0xFFFFFF, ax = 0.5, ay = 0.0):
    text = label.Label(font, text = txt, color = color)
    text.anchor_point = (ax, ay)
    text.anchored_position = (x, y)
    group.append(text)
    return text

def loadBitmapFonts():
    global fonts
    for key in fonts:
        bmp, palette = adafruit_imageload.load(fonts[key]['file'], bitmap = displayio.Bitmap, 
                                               palette = displayio.Palette)
        palette.make_transparent(0)
        fonts[key]['bmp'] = bmp
        fonts[key]['palette'] = palette

def addChar(group, font, char, x, y):
    global fonts
    char_grid = displayio.TileGrid(fonts[font]['bmp'], pixel_shader = fonts[font]['palette'], 
                                   width = 1, height = 1,
                                   tile_width = fonts[font]['size'], 
                                   tile_height = fonts[font]['size'], default_tile = 0)
    group.append(char_grid)
    setChar(char_grid, font, char, x, y)
    return char_grid

def setChar(chGrid, font, char, x = None, y = None):
    global fonts
    chGrid[0, 0] = fonts[font]['chars'].index(char)
    if x:
        chGrid.x = x
    if y:
        chGrid.y = y

def addText(group, font, txt, x, y, spacing = 1.2):
    global fonts
    grids = []
    for ch in txt:
        grids.append(addChar(group, font, ch, int(x), y))
        i = fonts[font]['chars'].index(ch)
        x += fonts[font]['chsize'][i] * spacing
    return grids

def setText(grids, font, txt, x, y, spacing = 1.2):
    for n, g in enumerate(grids):
        i = fonts[font]['chars'].index(txt[n])
        setChar(g, font, txt[n], int(x), y)
        x += fonts[font]['chsize'][i] * spacing

def initWidgets():
    global lblTime, lblDate, lblTemp
    loadBitmapFonts()
    group = displayio.Group()
    addImage(group, displayio.OnDiskBitmap('images/display.bmp'))
    lblTime = addTextOld(group, '--:--', BIGFONT, 80, 3)
    lblTemp = addTextOld(group, '00', ORANGEFONT, 0, 99, 0xFF6B0D, 0.0, 0.0)

    txt = addText(group, 'lens_20', '01.01.20', 5, 100)
    setText(txt, 'lens_20', '01.01.23', 50, 103)

    display.show(group)

def updateTime():
    if DEBUG:
        return
    try:
        pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(pool, tz_offset = int(os.getenv("TIME_OFFSET")))
        rtc.RTC().datetime = ntp.datetime
    except Exception as e:
        print("ntp failed", str(e))

# globals

SCK = board.GP10
SDA = board.GP11
AO = board.GP16
RESET = board.GP17
CS = board.GP18
BIGFONT = bitmap_font.load_font('fonts/camera_lens-52.bdf')
ORANGEFONT = bitmap_font.load_font('fonts/camera_lens-30.bdf')
SMALLFONT = bitmap_font.load_font('fonts/camera_lens-18.bdf')
fonts = {
    'lens_20': {
        'file': 'fonts/camera_lens_font_20.bmp', 
        'size': 20,
        'chars': '0123456789:.-O',
        'chsize': [638 / 50, 348 / 50, 647 / 50, 622 / 50, 662 / 50, 638 / 50, 628 / 50, 676 / 50, 
                638 / 50, 638 / 50, 152 / 50, 151 / 50, 595 / 50, 1000 / 50]
    }
}
TICK = 0.5
ticks = {'current': 0}


DEBUG = True

display = None 
lblTime = None
lblDate = None
lblTemp = None

main()


