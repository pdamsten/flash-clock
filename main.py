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

import gc
import displayio
from adafruit_st7735r import ST7735R
import board
import busio
import socketpool
import wifi
import rtc
import os
import time
import ssl
import adafruit_requests
import adafruit_ntp
from adafruit_datetime import datetime, timedelta

def main():
    global display

    connectWifi()
    initDisplay()
    loadBitmapFonts()
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
    setText(lblDate, 'lens_20', formatDate(), 50, 100)

def hourly():
    if guard('temp', 1800):
        print('Updating temperature')
        temp = getTemp()
        print('**', temp)
        setText(lblTemp, 'lens_30', formatTemp(temp), 0, 94)
    setText(lblTimeH, 'lens_50', formatTime()[:2], 0, 3)

def minutes():
    print('Updating time')
    setText(lblTimeM, 'lens_50', formatTime()[2:], 90, 3)

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
    return f'{(date.hour + isEUDst(date)):0=2}{date.minute:0=2}'

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

def background(group):
    b = displayio.OnDiskBitmap('images/display.bmp')
    bmp = displayio.TileGrid(b, pixel_shader = b.pixel_shader)
    group.append(bmp)

def addImage(group, bitmap, x = None, y = None):
    bmp = displayio.TileGrid(bitmap, pixel_shader = bitmap.pixel_shader)
    group.append(bmp)
    if x:
        bmp.x = x
    if y:
        bmp.y = y
    return bmp

def loadBitmapFonts():
    global fonts

    for key in fonts:
        fonts[key]['bmp'] = displayio.OnDiskBitmap(fonts[key]['file'])
        fonts[key]['bmp'].pixel_shader.make_transparent(0)

def addChar(group, font, char, x, y):
    global fonts
    char_grid = displayio.TileGrid(fonts[font]['bmp'], 
                                   pixel_shader = fonts[font]['bmp'].pixel_shader, 
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
    global lblTimeH, lblTimeM, lblDate, lblTemp
    gc.collect()
    group = displayio.Group()
    background(group)
    lblTimeH = addText(group, 'lens_50', '00', 0, 3)
    lblTimeM = addText(group, 'lens_50', '00', 90, 3)
    lblDate = addText(group, 'lens_20', '00.00.00', 20, 100)
    lblTemp = addText(group, 'lens_30', '00', 0, 94)

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
fonts = {
    'lens_50': {
        'file': 'fonts/camera_lens_font_50.bmp', 
        'size': 50,
        'chars': '0123456789',
        'chsize': [638 / 20, 348 / 20, 647 / 20, 622 / 20, 662 / 20, 638 / 20, 628 / 20, 676 / 20, 
                   638 / 20, 638 / 20]
    },
    'lens_30': {
        'file': 'fonts/camera_lens_font_30.bmp', 
        'size': 30,
        'chars': '0123456789-+',
        'chsize': [638 / 33.3, 348 / 33.3, 647 / 33.3, 622 / 33.3, 662 / 33.3, 638 / 33.3, 
                   628 / 33.3, 676 / 33.3, 638 / 33.3, 638 / 33.3, 718 / 33.3, 718 / 33.3]
    },
    'lens_20': {
        'file': 'fonts/camera_lens_font_20.bmp', 
        'size': 20,
        'chars': '0123456789.',
        'chsize': [638 / 50, 348 / 50, 647 / 50, 622 / 50, 662 / 50, 638 / 50, 628 / 50, 676 / 50, 
                   638 / 50, 638 / 50, 152 / 50, 151 / 50, 595 / 50, 1000 / 50]
    },
}
TICK = 0.5
ticks = {'current': 0}


DEBUG = False

display = None 
lblTimeH = None
lblTimeM = None
lblDate = None
lblTemp = None

main()


