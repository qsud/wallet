import telebot
from datetime import datetime
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import logging

logging.basicConfig(filename="bot_errors.log", level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")

bot = telebot.TeleBot("7698859036:AAG7jRRL58BTtbSv8Wf6kd_uHub3lshUr3c")

registered_users = {}

wallets = {
    "trojan": "9yMwSPk9mrXSN7yDHUuZurAh1sjbJsfpUqjZ7SvVtdco",
    "bonk": "ZG98FUCjb8mJ824Gbs6RsgVmr1FhXb2oNiJHa2dwmPd",
    "photon": "AVUCZyuT35YSuj4RH7fwiyPu82Djn2Hfg7y2ND2XcnZH",
    "bullx": "F4hJ3Ee3c5UuaorKAMfELBjYCjiiLH75haZTKqTywRP3"
}

ADMIN_UIDS_FILE = "admin_uid.txt"
if not os.path.exists(ADMIN_UIDS_FILE):
    open(ADMIN_UIDS_FILE, "w").close()

def load_admin_uids():
    with open(ADMIN_UIDS_FILE, "r") as f:
        return [int(line.strip()) for line in f if line.strip()]

def is_admin(user_id):
    admin_uids = load_admin_uids()
    return user_id in admin_uids

def remove_expired_users():
    while True:
        current_time = datetime.now()
        expired_users = [uid for uid, exp_time in registered_users.items() if current_time > exp_time]
        for uid in expired_users:
            del registered_users[uid]
            bot.send_message(uid, "Your premium access has expired.")
        threading.Event().wait(60)

threading.Thread(target=remove_expired_users, daemon=True).start()

scanning_event = threading.Event()
current_scanning_user = None

def get_signatures(wallet_address):
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            wallet_address,
            {"limit": 100}
        ]
    }
    response = requests.post(url, json=payload, headers=headers)
    signatures_data = response.json()
    return [entry["signature"] for entry in signatures_data.get("result", [])]

def get_sender_for_signature(signature):
    headers = {
        'authority': 'api.solana.fm',
        'accept': 'application/json, text/plain, */*',
        'user-agent': 'Mozilla/5.0'
    }
    url = f'https://api.solana.fm/v0/transfers/{signature}'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        try:
            source = data['result']['data'][0]['source']
            return source
        except (IndexError, KeyError):
            return None
    return None

def get_bearer_token():
    try:
        with open("config.txt", "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        print("config.txt not found.")
        return None

def fetch_wallet_data(source, minimum_winrate, minimum_pnl, wallet_name):
    bearer_token = get_bearer_token()
    headers = {
        'Accept': '*/*',
        'Authorization': f'Bearer {bearer_token}',
    }

    params = {
        'wallet': source,
        'skip_unrealized_pnl': 'true',
        'page': '1',
    }

    try:
        response = requests.get('https://feed-api.cielo.finance/v1/pnl/tokens', params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        winrate = round(data["data"]["winrate"], 2)
        tokens_traded = data["data"]["total_tokens_traded"]
        pnl = round(data["data"]["total_roi_percentage"], 2)

        if winrate > minimum_winrate and pnl > minimum_pnl:
            return f"⛓ Detected Wallet— {wallet_name}\n\n{source}\n\nWin Rate: {winrate}\nLast 7D PnL: {pnl}\nTokens Traded: {tokens_traded}"
    except requests.exceptions.RequestException:
        pass
    except KeyError:
        pass
    return None

def print_all_senders(wallet_name, minimum_winrate, minimum_pnl, user_id):
    global current_scanning_user
    scanning_event.set()
    wallet_address = wallets.get(wallet_name.lower())
    if not wallet_address:
        bot.send_message(user_id, "Invalid wallet name. Please choose a valid wallet.")
        scanning_event.clear()
        current_scanning_user = None
        return

    while scanning_event.is_set():
        signatures = get_signatures(wallet_address)
        approved_wallets = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            sender_futures = [executor.submit(get_sender_for_signature, signature) for signature in signatures]
            sources = [future.result() for future in as_completed(sender_futures) if future.result()]

            for source in sources:
                if not scanning_event.is_set():
                    return
                result = fetch_wallet_data(source, minimum_winrate, minimum_pnl, wallet_name)
                if result:
                    approved_wallets.append(result)
                    bot.send_message(user_id, result)

        time.sleep(5)

@bot.message_handler(commands=['on'])
def on_command(message):
    bot.reply_to(message, "I am active")

@bot.message_handler(commands=['scan'])
def scan_wallet(message):
    global current_scanning_user
    user_id = message.from_user.id

    if scanning_event.is_set():
        bot.send_message(user_id, f"Another scan is in progress by user {current_scanning_user}. Please stop it using /kill first.")
        return

    try:
        _, wallet_name, _, min_winrate, _, min_pnl = message.text.split()
        min_winrate, min_pnl = float(min_winrate), float(min_pnl)
    except ValueError:
        bot.send_message(user_id, "Invalid format. Use /scan {wallet_name} winrate {minimum_winrate} pnl {minimum_pnl}.")
        return

    current_scanning_user = user_id
    bot.send_message(user_id, "Starting scan...\n\nSend /kill to stop.")
    print_all_senders(wallet_name, min_winrate, min_pnl, user_id)

@bot.message_handler(commands=['kill'])
def kill_scan(message):
    global current_scanning_user
    user_id = message.from_user.id

    if not scanning_event.is_set():
        bot.send_message(user_id, "No scan is currently in progress.")
        return

    if current_scanning_user != user_id:
        bot.send_message(user_id, "You are not authorized to stop this scan.")
        return

    scanning_event.clear()
    current_scanning_user = None
    bot.send_message(user_id, "Scan process stopped.")

@bot.message_handler(commands=['replace_admin_list'])
def replace_admin_list(message):
    user_id = message.from_user.id
    bot.send_message(user_id, "Please send me the admin list file (a .txt file).")

@bot.message_handler(content_types=['document'])
def handle_admin_list_file(message):
    file_info = bot.get_file(message.document.file_id)
    if not file_info.file_path.endswith('.txt'):
        bot.reply_to(message, "Invalid file format. Please send a valid .txt file.")
        return
    downloaded_file = bot.download_file(file_info.file_path)
    try:
        with open(ADMIN_UIDS_FILE, "wb") as admin_file:
            admin_file.write(downloaded_file)
        bot.send_message(message.chat.id, "Admin list updated successfully.")
    except Exception:
        bot.send_message(message.chat.id, "An error occurred while updating the admin list.")

@bot.message_handler(commands=['config'])
def handle_config(message):
    global current_scanning_user
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "Access denied. You are not registered.")
        return

    if scanning_event.is_set():
        bot.send_message(user_id, f"A scan is currently in progress by user {current_scanning_user}. Please stop it using /kill before updating the configuration.")
        return

    try:
        config_data = message.text.split(" ", 1)[1]
    except IndexError:
        bot.reply_to(message, "No configuration data provided. Please send /config {config_data}.")
        return

    try:
        if os.path.exists("config.txt"):
            os.remove("config.txt")
        with open("config.txt", "w") as config_file:
            config_file.write(config_data)
        bot.send_message(user_id, "Configuration updated successfully.")
    except Exception as e:
        bot.send_message(user_id, f"An error occurred: {str(e)}")

@bot.message_handler(commands=['start'])
def start_command(message):
    username = message.from_user.first_name
    bot.reply_to(
        message,
        f"""**Welcome, {username}, to our Bot!**  
Your reliable assistant for Wallet Detection.

💼 **What We Offer:**  
- Target custom PnL wallets  
- Target custom win-rate wallets  
- Target minimum trades  

🔍 **How to Use Commands:**  
Use `/scan {{wallet_name}} winrate {{minimum_winrate}} pnl {{minimum_pnl}}` to get started.

💼 **Available Wallets to Scan:**  
- trojan  
- bonk  
- photon  
- bullx  

🛡️ **Your privacy and security are our top priorities.**  

Thank you for choosing our Bot, {username}!
        """,
        parse_mode="Markdown"
    )

def restart_bot():
    """Automatically restart the bot in case of an error."""
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logging.error(f"Bot stopped due to error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=restart_bot).start()

