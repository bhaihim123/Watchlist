#!/usr/bin/env python3
#telegram- brocodx

import requests
import json
import time
import os
import logging
from datetime import datetime
from pathlib import Path
import telebot
import threading
import sys
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WISHLIST_API = "https://www.sheinindia.in/api/wishlist/getwishlist"

TELEGRAM_BOT_TOKEN = "8550463664:AAGq23HF3tX-82Fy8E69eeHDquX7J9ug6rE"
TELEGRAM_CHAT_ID = "7575574860"

session = requests.Session()
session.verify = False

import telebot.apihelper
telebot.apihelper.session = session

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

CHECK_INTERVAL = 3
TOTAL_PAGES = 9
PAGE_SIZE = 10
REQUEST_TIMEOUT = 10
MAX_RETRIES = 5
MAX_NOTIFICATIONS_PER_PRODUCT = 3

LOG_FILE = "wishlist_monitor.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger()

NOTIFICATION_COUNT_FILE = "notification_count.json"

def load_notification_counts():
    if os.path.exists(NOTIFICATION_COUNT_FILE):
        try:
            with open(NOTIFICATION_COUNT_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_notification_counts(c):
    with open(NOTIFICATION_COUNT_FILE,"w") as f:
        json.dump(c,f,indent=2)

NOTIFICATION_COUNTS = load_notification_counts()

PREVIOUS_STOCK_STATUS = {}

MONITORING_ACTIVE = False
MONITOR_THREAD = None


def parse_cookie_header(cookie_string):
    cookies={}
    for pair in cookie_string.split(";"):
        if "=" in pair:
            k,v=pair.strip().split("=",1)
            cookies[k]=v
    return cookies


def save_cookies(cookies):
    os.makedirs("cookies",exist_ok=True)
    with open("cookies/cookies.json","w") as f:
        json.dump(cookies,f,indent=2)


def load_cookies():
    p=Path("cookies/cookies.json")
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def send_telegram_message(msg):
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url,json={
            "chat_id":TELEGRAM_CHAT_ID,
            "text":msg,
            "parse_mode":"Markdown"
        })
    except Exception as e:
        logger.error(e)


def fetch_page(cookies,page):
    params={
        "currentPage":page,
        "pageSize":PAGE_SIZE,
        "store":"shein"
    }

    headers={
        "User-Agent":"Mozilla/5.0"
    }

    try:
        r=session.get(WISHLIST_API,params=params,cookies=cookies,headers=headers,timeout=REQUEST_TIMEOUT)
        if r.status_code!=200:
            return []
        return r.json().get("products",[])
    except:
        return []


def extract_wishlist_products(cookies):

    in_stock=[]
    total=0

    for page in range(TOTAL_PAGES+1):

        products=fetch_page(cookies,page)

        if not products:
            break

        for product in products:

            total+=1

            code=product.get("productCode","")
            name=product.get("name","Unknown")

            if "variantOptions" in product:

                for v in product["variantOptions"]:

                    stock=v.get("stock",{})

                    if stock.get("stockLevelStatus")=="inStock":

                        size="Unknown"

                        for q in v.get("variantOptionQualifiers",[]):
                            if q["qualifier"]=="size":
                                size=q["value"]

                        in_stock.append({
                            "productCode":code,
                            "name":name,
                            "size":size,
                            "price":product.get("price",{}).get("value",0),
                            "url":product.get("url","")
                        })

    return in_stock,total


@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(m.chat.id,"Bot online\nUse /setcookies")


@bot.message_handler(commands=["setcookies"])
def setcookies(m):
    msg=bot.send_message(m.chat.id,"Send cookies.txt")
    bot.register_next_step_handler(msg,process_cookies)


def process_cookies(message):

    if not message.document:
        bot.send_message(message.chat.id,"Send file")
        return

    file=bot.get_file(message.document.file_id)
    data=bot.download_file(file.file_path)

    cookie_string=data.decode()

    cookies=parse_cookie_header(cookie_string)

    save_cookies(cookies)

    bot.send_message(message.chat.id,"Cookies saved")


@bot.message_handler(commands=["startmonitor"])
def start_monitor(m):

    global MONITORING_ACTIVE,MONITOR_THREAD

    if MONITORING_ACTIVE:
        bot.send_message(m.chat.id,"Already running")
        return

    MONITORING_ACTIVE=True

    MONITOR_THREAD=threading.Thread(target=monitor_wishlist)
    MONITOR_THREAD.start()

    bot.send_message(m.chat.id,"Monitor started")


@bot.message_handler(commands=["stopmonitor"])
def stop_monitor(m):

    global MONITORING_ACTIVE

    MONITORING_ACTIVE=False

    bot.send_message(m.chat.id,"Monitor stopped")


def monitor_wishlist():

    global MONITORING_ACTIVE,PREVIOUS_STOCK_STATUS

    cookies=load_cookies()

    scan=0

    try:

        while MONITORING_ACTIVE:

            scan+=1

            start=time.time()

            products,total=extract_wishlist_products(cookies)

            notified=0

            for p in products:

                code=p["productCode"]

                was=PREVIOUS_STOCK_STATUS.get(code,False)

                PREVIOUS_STOCK_STATUS[code]=True

                if was:
                    continue

                msg=f"""
🔔 *IN STOCK*

{p['name']}
Size: {p['size']}
Price: {p['price']}

https://www.sheinindia.in/product-{code}.html
"""

                send_telegram_message(msg)

                notified+=1

            duration=time.time()-start

            logger.info(f"Scan {scan} | {duration:.1f}s | {notified} alerts")

            time.sleep(CHECK_INTERVAL)

    except Exception as e:

        logger.error(e)

    finally:

        MONITORING_ACTIVE=False
        logger.info("Monitor stopped")


if __name__=="__main__":

    while True:
        try:
            bot.infinity_polling()
        except Exception as e:
            logger.error(e)
            time.sleep(5)
