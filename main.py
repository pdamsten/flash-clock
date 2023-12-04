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
import os, sys
import time
import ssl
import adafruit_requests
import adafruit_ntp
from adafruit_datetime import datetime, timedelta
import microcontroller

def main():
    global display, keep_error

    initDisplay()
    loadBitmapFonts()
    initWidgets()

    pdate = datetime.now() - timedelta(days = 1, minutes = 1, hours = 1)
    while True:
        if guard('error', keep_error):
            clear_error()
        d = datetime.now()
        if pdate.day != d.day:
            try:
                daily()
            except Exception as e:
                print("daily failed", str(e))
                error_code(201)
        if pdate.hour != d.hour:
            try:
                hourly()
            except Exception as e:
                print("hourly failed", str(e))
                error_code(202)
        if pdate.minute != d.minute:
            try:
                minutes()
            except Exception as e:
                print("minutes failed", str(e))
                error_code(203)
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
    print('.', end = '')

def daily():
    print('Updating date & ntp')
    if guard('time', 3600):
        updateTime()
    print('**', datetime.now())
    if SHOWDATE:
        setText(lblDate, formatDate())

def hourly():
    if guard('temp', 1800):
        print('Updating temperature')
        temp = getTemp()
        print('**', temp)
        setText(lblTemp, formatTemp(temp))
        setText(lblDot, '+' if temp >= 0.0 else '-')
    setText(lblTimeH, formatTime()[:2])

def minutes():
    print('Updating time')
    setText(lblTimeM, formatTime()[2:])

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

def error_code(code, keep = 12 * 60 *60):
    global keep_error, ticks
    if SHOWERROR == 1:
        setText(lblDate, f'  {code:0=3}   ')
        keep_error = keep
        ticks['error'] = ticks['current']

def clear_error():
    global keep_error
    if SHOWERROR == 1:
        setText(lblDate, f'        ')
        keep_error = sys.maxsize

def checkWifi():    
    if DEBUG:
        return
    for i in range(5):
        try:
            if wifi.radio.connected:
                break
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
        except Exception as e:
            print('Wifi failed', str(e))
            error_code(300 + i + 1, i * 3600 + 30)
            time.sleep(i * 10 + 0.5)

    if not wifi.radio.connected:
        print("Resetting clock in 5 seconds")
        error_code(401)
        time.sleep(5)
        microcontroller.reset()

def getTemp():
    if DEBUG:
        return 28.0
    url = 'https://api.open-meteo.com/v1/forecast?latitude=' + \
           LATITUDE + '&longitude=' + LONGITUDE + '&current=temperature_2m'
    data = getJson(url)
    return data['current']['temperature_2m']

def getJson(url):
    data = {}
    checkWifi()
    try:
        pool = socketpool.SocketPool(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl.create_default_context())
        response = requests.get(url)
        data = response.json()
        response.close()
    except Exception as e:
        error_code(501)
        print("json failed", str(e))
    return data

def initDisplay():
    global display
    displayio.release_displays()
    spi = busio.SPI(clock = SCK, MOSI = SDA)
    dbus = displayio.FourWire(spi, command = AO, chip_select = CS, reset = RESET)
    display = ST7735R(dbus, width = 160, height = 128, rotation = 90, bgr = True)

def color(clr, extra = 1.0):
    b = clr % 256
    g = (clr >> 8) % 256
    r = (clr >> 16)

    r *= (BRIGHTNESS / 100.0) * extra
    g *= (BRIGHTNESS / 100.0) * 0.8 * extra
    b *= (BRIGHTNESS / 100.0) * 0.7 * extra

    return (int(r) << 16 | int(g) << 8 | int(b))

def dimPalette(org, extra = 1.0):
    if BRIGHTNESS == 100:
        return org
    palette = displayio.Palette(len(org))
    for c in range(len(org)):
        palette[c] = color(org[c], extra)
    return palette

def background(group):
    b = displayio.OnDiskBitmap('images/display.bmp')
    bmp = displayio.TileGrid(b, pixel_shader = dimPalette(b.pixel_shader))
    group.append(bmp)

def loadBitmapFonts():
    global fonts

    for key in fonts:
        fonts[key]['bmp'] = displayio.OnDiskBitmap(fonts[key]['file'])
        fonts[key]['palette'] = dimPalette(fonts[key]['bmp'].pixel_shader, fonts[key]['dimextra'])
        fonts[key]['palette'].make_transparent(0)

def addChar(group, font):
    global fonts
    char_grid = displayio.TileGrid(fonts[font]['bmp'], 
                                   pixel_shader = fonts[font]['palette'], 
                                   width = 1, height = 1,
                                   tile_width = fonts[font]['size'], 
                                   tile_height = fonts[font]['size'], default_tile = 0)
    group.append(char_grid)
    return char_grid

def setChar(chGrid, font, char, x = None, y = None):
    global fonts

    chGrid[0, 0] = fonts[font]['chars'].index(char)
    if x:
        chGrid.x = int(x)
    if y:
        chGrid.y = int(y)

def textSize(label, txt):
    global fonts
    w = 0
    h = fonts[label['font']]['size']
    for n, ch in enumerate(txt):
        i = fonts[label['font']]['chars'].index(ch)
        size = fonts[label['font']]['chsize'][i] 
        spacing = size[1] if isinstance(size, tuple) else fonts[label['font']]['spacing']
        size = size[0] if isinstance(size, tuple) else size
        if n < len(txt) - 1:
            w += size * spacing
        else:
            w += size
    return (w, h)

def addText(group, font, txt, x, y):
    global fonts
    label = {}
    label['grids'] = []
    label['font'] = font
    x = x if isinstance(x, tuple) else ('L', x)
    y = y if isinstance(y, tuple) else ('L', y)
    label['pos'] = (x, y)
    for ch in txt:
        label['grids'].append(addChar(group, font))
    setText(label, txt)
    return label

def setText(label, txt):
    size = textSize(label, txt)
    x = label['pos'][0][1]
    y = label['pos'][1][1]
    x -= size[0] if label['pos'][0][0] == 'R' else 0
    x -= size[0] / 2 if label['pos'][0][0] == 'C' else 0
    y -= size[1] if label['pos'][1][0] == 'B' else 0
    y -= size[1] / 2 if label['pos'][1][0] == 'M' else 0

    for n, g in enumerate(label['grids']):
        i = fonts[label['font']]['chars'].index(txt[n])
        setChar(g, label['font'], txt[n], x, y)
        size = fonts[label['font']]['chsize'][i] 
        spacing = size[1] if isinstance(size, tuple) else fonts[label['font']]['spacing']
        size = size[0] if isinstance(size, tuple) else size
        x += size * spacing

def initWidgets():
    global lblTimeH, lblTimeM, lblDate, lblTemp, lblDot
    gc.collect()
    group = displayio.Group()
    background(group)
    lblTimeH = addText(group, 'lens_50', '00', ('R', SCREEN_WIDTH / 2 - 10), MARGIN)
    lblTimeM = addText(group, 'lens_50', '00', ('L', SCREEN_WIDTH / 2 + 10), MARGIN)
    lblDate = addText(group, 'lens_17', '        ', 
                      ('C', SCREEN_WIDTH / 2 + 10), ('B', SCREEN_HEIGHT - MARGIN - 6))
    x = ('R', 40 + MARGIN) if SHOWDATE else ('L', 2 * MARGIN)
    lblTemp = addText(group, 'lens_30', '00', x, ('B', SCREEN_HEIGHT - MARGIN))
    lblDot = addText(group, 'lens_30', '+', 
                     ('R', SCREEN_WIDTH - MARGIN), ('B', SCREEN_HEIGHT - MARGIN))

    display.show(group)

def updateTime():
    if DEBUG:
        rtc.RTC().datetime = time.struct_time((2020, 3, 27, 19, 10, 0, 0, -1, -1))
        return
    checkWifi()
    try:
        pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(pool, tz_offset = TIME_OFFSET)
        rtc.RTC().datetime = ntp.datetime
    except Exception as e:
        error_code(601)
        print("ntp failed", str(e))

# globals
SCREEN_WIDTH = 160
SCREEN_HEIGHT = 128
MARGIN = 3

SCK = board.GP10
SDA = board.GP11
AO = board.GP16
RESET = board.GP17
CS = board.GP18
fonts = {
    'lens_50': {
        'file': 'fonts/camera_lens_font_50.bmp', 
        'size': 50,
        'spacing': 1.1,
        'dimextra': 0.8,
        'chars': '0123456789',
        'chsize': [638 / 20, (348 / 20, 1.3), 647 / 20, 622 / 20, 662 / 20, 638 / 20, 
                   628 / 20, 676 / 20, 638 / 20, 638 / 20]
    },
    'lens_30': {
        'file': 'fonts/camera_lens_font_30.bmp', 
        'size': 30,
        'spacing': 1.2,
        'dimextra': 1.0,
        'chars': '0123456789-+',
        'chsize': [638 / 33.3, 348 / 33.3, 647 / 33.3, 622 / 33.3, 662 / 33.3, 638 / 33.3, 
                   628 / 33.3, 676 / 33.3, 638 / 33.3, 638 / 33.3, 718 / 33.3, 718 / 33.3]
    },
    'lens_17': {
        'file': 'fonts/camera_lens_font_17.bmp', 
        'size': 17,
        'spacing': 1.1,
        'dimextra': 1.0,
        'chars': '0123456789. ',
        'chsize': [638 / (1000/17), 348 / (1000/17), 647 / (1000/17), 622 / (1000/17), 
                   662 / (1000/17), 638 / (1000/17), 628 / (1000/17), 676 / (1000/17), 
                   638 / (1000/17), 638 / (1000/17), 152 / (1000/17), 500 / (1000/17)]
    },
}

TICK = 0.5
ticks = {'current': 0}
keep_error = 0

DEBUG = (int(os.getenv('DEBUG', 0)) == 1)
SHOWDATE = (int(os.getenv('SHOWDATE', 1)) == 1)
SHOWERROR = (int(os.getenv('SHOW_ERROR_CODES', 0)) ==1)
WIFI_SSID = os.getenv('WIFI_SSID', '')
WIFI_PASSWORD = os.getenv('WIFI_PASSWORD', '')
LATITUDE = os.getenv('WEATHER_LATITUDE', 51.4934)
LONGITUDE = os.getenv('WEATHER_LONGITUDE', 0)
TIME_OFFSET = int(os.getenv('TIME_OFFSET', 0))
BRIGHTNESS = int(os.getenv('BRIGHTNESS', 100))

display = None 
lblTimeH = None
lblTimeM = None
lblDate = None
lblTemp = None

main()


