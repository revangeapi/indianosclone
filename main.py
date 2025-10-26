import logging
import asyncio
import sqlite3
import threading
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import aiohttp
import json
import random
from flask import Flask, request, jsonify
import requests
import time

# Bot Configuration
BOT_TOKEN = "7312642236:AAGns6nuCIRin80VMcTytLvAI6CKzCd7uEI"
REQUIRED_CHANNELS = ["@anshapi", "@revangeosint"]
ADMIN_ID = 6258915779
API_URL = "https://numapi.anshapi.workers.dev/?num="
AADHAR_API_URL = "https://addartofamily.vercel.app/fetch"
AADHAR_API_KEY = "fxt"
PORTS = list(range(5000, 10001))  # 5000 ports from 5000 to 10000

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask App
flask_app = Flask(__name__)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_clones.db', check_same_thread=False)
        self.create_tables()
        
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                clone_token TEXT,
                clone_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def add_clone(self, user_id, clone_token, clone_name):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO clones (user_id, clone_token, clone_name) VALUES (?, ?, ?)',
            (user_id, clone_token, clone_name)
        )
        self.conn.commit()

    def get_clones(self, user_id=None):
        cursor = self.conn.cursor()
        if user_id:
            cursor.execute('SELECT * FROM clones WHERE user_id = ?', (user_id,))
        else:
            cursor.execute('SELECT * FROM clones')
        return cursor.fetchall()

    def add_broadcast(self, admin_id, message):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO broadcasts (admin_id, message) VALUES (?, ?)',
            (admin_id, message)
        )
        self.conn.commit()
        return cursor.lastrowid

    def log_activity(self, user_id, action, data=None):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO user_activity (user_id, action, data) VALUES (?, ?, ?)',
            (user_id, action, data)
        )
        self.conn.commit()

@flask_app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Phone Lookup & Aadhar Bot",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "/health": "Health check",
            "/stats": "Bot statistics",
            "/webhook": "Telegram webhook (if configured)"
        }
    })

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@flask_app.route('/stats')
def stats():
    db = Database()
    clones = db.get_clones()
    return jsonify({
        "total_clones": len(clones),
        "active_since": datetime.now().isoformat(),
        "service": "Dual API Bot"
    })

@flask_app.route('/aadhar_api')
def aadhar_api_proxy():
    """Proxy for Aadhar API to handle CORS"""
    aadhaar_number = request.args.get('aadhaar')
    if not aadhaar_number:
        return jsonify({"error": "Aadhaar number required"}), 400
    
    try:
        response = requests.get(
            f"{AADHAR_API_URL}?aadhaar={aadhaar_number}&key={AADHAR_API_KEY}",
            timeout=30
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_flask():
    """Run Flask server on port 8080"""
    flask_app.run(host='0.0.0.0', port=8080, debug=False)

class CloneBotManager:
    """Manages clone bots to avoid conflicts"""
    def __init__(self, main_bot):
        self.main_bot = main_bot
        self.clone_processes = {}
        self.running_clones = set()
        
    def start_clone_bot(self, bot_token, owner_id, clone_name):
        """Start a clone bot in separate process to avoid conflicts"""
        if bot_token in self.running_clones:
            logger.info(f"Clone bot {clone_name} is already running")
            return
            
        def run_clone():
            try:
                # Add delay to avoid immediate conflict
                time.sleep(2)
                
                # Create new application instance
                clone_app = Application.builder().token(bot_token).build()
                
                # Setup basic handlers for clone bot
                clone_app.add_handler(CommandHandler("start", self.clone_start_command))
                clone_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.clone_handle_message))
                
                logger.info(f"🔄 Starting clone bot: {clone_name}")
                
                # Store in main bot's clone_bots dict
                self.main_bot.clone_bots[bot_token] = {
                    'app': clone_app,
                    'owner_id': owner_id,
                    'started_at': datetime.now(),
                    'name': clone_name
                }
                
                # Run the clone bot
                clone_app.run_polling(
                    allowed_updates=Update.ALL_TYPES,
                    close_loop=False
                )
                
            except Exception as e:
                logger.error(f"Clone bot {clone_name} error: {e}")
                if bot_token in self.running_clones:
                    self.running_clones.remove(bot_token)
        
        # Start in separate thread
        thread = threading.Thread(target=run_clone)
        thread.daemon = True
        thread.start()
        
        self.running_clones.add(bot_token)
        logger.info(f"✅ Clone bot {clone_name} started successfully")
        
    async def clone_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command for clone bots"""
        welcome_text = (
            "👋 *Welcome to Clone Bot!*\n\n"
            "This is a mirrored bot from the main Lookup service.\n\n"
            "Send me:\n"
            "• 10-digit phone number\n"
            "• 12-digit Aadhar number\n\n"
            "For automatic lookup!"
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def clone_handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Message handler for clone bots"""
        user_input = update.message.text.strip()
        
        # Auto-detect input type
        if user_input.isdigit():
            if len(user_input) == 10:
                await self.process_clone_phone_lookup(update, context, user_input)
            elif len(user_input) == 12:
                await self.process_clone_aadhar_lookup(update, context, user_input)
            else:
                await update.message.reply_text(
                    "❌ *Invalid input!*\n\n"
                    "Please send:\n"
                    "• 10-digit phone number\n"
                    "• 12-digit Aadhar number",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Please send only numbers!*\n\n"
                "📱 *Phone Lookup:* 10 digits\n"
                "🆔 *Aadhar Lookup:* 12 digits",
                parse_mode='Markdown'
            )

    async def process_clone_phone_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone_number: str):
        """Process phone lookup for clone bot"""
        processing_msg = await update.message.reply_text(
            "📱 *Phone Lookup in Progress...*\n\n"
            "▰▰▰▰▰▰▰▰▰▰ 0%",
            parse_mode='Markdown'
        )
        
        try:
            # Simulate progress
            for i in range(1, 6):
                await asyncio.sleep(0.3)
                progress = i * 20
                bars = "▰" * i + "▱" * (5 - i)
                await processing_msg.edit_text(
                    f"📱 *Phone Lookup in Progress...*\n\n"
                    f"{bars} {progress}%",
                    parse_mode='Markdown'
                )
            
            # Use main bot's method to fetch data
            data = await self.main_bot.fetch_phone_data(phone_number)
            
            await processing_msg.delete()
            
            if data:
                formatted_message = self.main_bot.format_phone_data(data)
                await update.message.reply_text(formatted_message, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ *Error fetching phone data. Please try again later.*", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Clone bot phone lookup error: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text("❌ *An error occurred while processing your request.*", parse_mode='Markdown')

    async def process_clone_aadhar_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, aadhaar_number: str):
        """Process Aadhar lookup for clone bot"""
        processing_msg = await update.message.reply_text(
            "🆔 *Aadhar Family Lookup in Progress...*\n\n"
            "▰▰▰▰▰▰▰▰▰▰ 0%",
            parse_mode='Markdown'
        )
        
        try:
            # Simulate progress
            for i in range(1, 6):
                await asyncio.sleep(0.3)
                progress = i * 20
                bars = "▰" * i + "▱" * (5 - i)
                await processing_msg.edit_text(
                    f"🆔 *Aadhar Family Lookup in Progress...*\n\n"
                    f"{bars} {progress}%",
                    parse_mode='Markdown'
                )
            
            # Use main bot's method to fetch data
            data = await self.main_bot.fetch_aadhar_data(aadhaar_number)
            
            await processing_msg.delete()
            
            if data:
                formatted_message = self.main_bot.format_aadhar_data(data)
                await update.message.reply_text(formatted_message, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ *Error fetching Aadhar data. Please try again later.*", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Clone bot Aadhar lookup error: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text("❌ *An error occurred while processing your Aadhar request.*", parse_mode='Markdown')

class PhoneLookupBot:
    def __init__(self):
        self.db = Database()
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.clone_manager = CloneBotManager(self)
        self.setup_handlers()
        self.clone_bots = {}  # Store active clone bots info

    def setup_handlers(self):
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("check", self.check_membership))
        self.application.add_handler(CommandHandler("clone", self.clone_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("port", self.port_command))
        self.application.add_handler(CommandHandler("aadhar", self.aadhar_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Message handler for both phone numbers and aadhar numbers
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_user_input))
        
        # Callback query handlers
        self.application.add_handler(CallbackQueryHandler(self.membership_callback, pattern="^check_membership$"))
        self.application.add_handler(CallbackQueryHandler(self.force_join_callback, pattern="^force_join$"))

    async def is_member(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if user is member of required channels"""
        try:
            for channel in REQUIRED_CHANNELS:
                member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status in ['left', 'kicked']:
                    return False
            return True
        except Exception as e:
            logger.error(f"Error checking membership: {e}")
            return False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        
        # Send force join message with inline buttons
        keyboard = [
            [InlineKeyboardButton("Join Channel 1", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
            [InlineKeyboardButton("Join Channel 2", url=f"https://t.me/{REQUIRED_CHANNELS[1][1:]}")],
            [InlineKeyboardButton("✅ I've Joined", callback_data="force_join")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "🔒 *FORCE JOIN REQUIRED* 🔒\n\n"
            "To use this bot, you must join our official channels first!\n\n"
            "📢 Channels to join:\n"
            f"• {REQUIRED_CHANNELS[0]}\n"
            f"• {REQUIRED_CHANNELS[1]}\n\n"
            "Click the buttons below to join, then click 'I've Joined' to verify."
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Log the start command
        await self.log_action(update, f"User {user_id} started the bot")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🆘 *Bot Help Guide*\n\n"
            
            "📱 *Phone Lookup:*\n"
            "Simply send any 10-digit phone number\n"
            "*Example:* `9889662072`\n\n"
            
            "🆔 *Aadhar Family Info:*\n"
            "Send any 12-digit Aadhar number\n"
            "Or use: `/aadhar 658014451208`\n\n"
            
            "🤖 *Bot Commands:*\n"
            "`/start` - Start the bot\n"
            "`/aadhar` - Aadhar lookup\n"
            "`/clone` - Create clone bot\n"
            "`/port` - Get available port\n"
            "`/check` - Verify membership\n"
            "`/stats` - Admin statistics\n"
            "`/broadcast` - Admin broadcast\n\n"
            
            "🔧 *Services:*\n"
            "• Phone number information\n"
            "• Aadhar family details\n"
            "• Clone bot system\n"
            "• Multi-port support\n\n"
            
            "⚡ *Auto-detection:*\n"
            "Just send 10-digit (phone) or 12-digit (Aadhar) number!"
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def aadhar_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /aadhar command"""
        user_id = update.effective_user.id
        
        if not await self.is_member(user_id, context):
            await self.send_membership_required_message(update, context)
            return
        
        if not context.args:
            await update.message.reply_text(
                "🆔 *Aadhar Family Lookup*\n\n"
                "Usage: `/aadhar 658014451208`\n\n"
                "Or simply send any 12-digit Aadhar number directly!",
                parse_mode='Markdown'
            )
            return
        
        aadhaar_number = context.args[0]
        await self.process_aadhar_lookup(update, context, aadhaar_number)

    async def force_join_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle force join verification"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if await self.is_member(user_id, context):
            welcome_text = (
                "🎉 *Welcome to Multi-Service Lookup Bot!*\n\n"
                "📱 *Services Available:*\n"
                "• Phone number lookup\n"
                "• Aadhar family info\n"
                "• Clone bot creation\n"
                "• Stylish data formatting\n"
                "• Multi-port support\n\n"
                "🔍 *How to use:*\n"
                "Simply send:\n"
                "• 10-digit phone number\n"
                "• 12-digit Aadhar number\n\n"
                "⚡ *Examples:*\n"
                "`9889662072` - Phone lookup\n"
                "`658014451208` - Aadhar lookup\n\n"
                "💫 *Commands:*\n"
                "/aadhar - Aadhar lookup\n"
                "/clone - Create your own bot\n"
                "/port - Get available port\n"
                "/stats - Bot statistics\n"
                "/help - Show help guide"
            )
            await query.message.edit_text(welcome_text, parse_mode='Markdown')
        else:
            keyboard = [
                [InlineKeyboardButton("Join Channel 1", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
                [InlineKeyboardButton("Join Channel 2", url=f"https://t.me/{REQUIRED_CHANNELS[1][1:]}")],
                [InlineKeyboardButton("✅ I've Joined", callback_data="force_join")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                "❌ *You haven't joined all channels yet!*\n\n"
                "Please join both channels and click 'I've Joined' again.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

    async def send_membership_required_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send message requiring channel membership"""
        keyboard = [
            [InlineKeyboardButton("Join Channel 1", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
            [InlineKeyboardButton("Join Channel 2", url=f"https://t.me/{REQUIRED_CHANNELS[1][1:]}")],
            [InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "🔒 *Access Denied!*\n\n"
            "You need to join our channels to use this feature:\n\n"
            f"• {REQUIRED_CHANNELS[0]}\n"
            f"• {REQUIRED_CHANNELS[1]}\n\n"
            "Join the channels above and verify your membership."
        )
        
        if update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def check_membership(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /check command to verify membership"""
        user_id = update.effective_user.id
        
        if await self.is_member(user_id, context):
            await update.message.reply_text("✅ *Access Granted!* You're a member of all required channels.", parse_mode='Markdown')
        else:
            await self.send_membership_required_message(update, context)

    async def membership_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle membership check callback"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if await self.is_member(user_id, context):
            await query.message.edit_text("✅ *Access Granted!* You're a member of all required channels.", parse_mode='Markdown')
        else:
            await self.send_membership_required_message(update, context)

    async def clone_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clone command to create bot clones"""
        user_id = update.effective_user.id
        
        if not await self.is_member(user_id, context):
            await self.send_membership_required_message(update, context)
            return
        
        if not context.args:
            await update.message.reply_text(
                "🤖 *Bot Clone System*\n\n"
                "To create your own clone bot, use:\n"
                "`/clone YOUR_BOT_TOKEN`\n\n"
                "*Example:*\n"
                "`/clone 1234567890:ABCdefGHIjklMNopQRstUVwxYZ`\n\n"
                "Get your bot token from @BotFather",
                parse_mode='Markdown'
            )
            return
        
        bot_token = context.args[0]
        
        # Validate bot token format
        if ':' not in bot_token or len(bot_token) < 20:
            await update.message.reply_text("❌ *Invalid bot token format!*", parse_mode='Markdown')
            return
        
        try:
            # Test the bot token
            test_bot = Bot(token=bot_token)
            bot_info = await test_bot.get_me()
            bot_name = bot_info.username
            
            # Store clone in database
            self.db.add_clone(user_id, bot_token, bot_name)
            
            # Start clone bot using manager (avoids conflicts)
            self.clone_manager.start_clone_bot(bot_token, user_id, bot_name)
            
            await update.message.reply_text(
                f"🎉 *Clone Bot Created Successfully!*\n\n"
                f"• Bot: @{bot_name}\n"
                f"• Token: `{bot_token[:10]}...`\n"
                f"• Owner: {user_id}\n\n"
                f"Your bot is now active and will mirror all broadcasts!\n\n"
                f"🔗 *Bot Link:* https://t.me/{bot_name}",
                parse_mode='Markdown'
            )
            
            # Log clone creation
            await self.log_action(update, f"User {user_id} created clone bot @{bot_name}")
            
        except Exception as e:
            error_msg = str(e)
            if "Conflict" in error_msg:
                error_msg = "Bot token is already being used by another running instance. Please stop other instances first."
            await update.message.reply_text(f"❌ *Error creating clone:* {error_msg}", parse_mode='Markdown')

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command (admin only)"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ *Admin only command!*", parse_mode='Markdown')
            return
        
        if not context.args:
            await update.message.reply_text(
                "📢 *Broadcast System*\n\n"
                "Usage: `/broadcast your message here`\n\n"
                "This will send the message to all users and clone bots.",
                parse_mode='Markdown'
            )
            return
        
        message = ' '.join(context.args)
        broadcast_id = self.db.add_broadcast(ADMIN_ID, message)
        
        sent_count = 0
        for clone_data in self.clone_bots.values():
            try:
                # Send broadcast to clone bot owners
                await self.application.bot.send_message(
                    chat_id=clone_data['owner_id'],
                    text=f"📢 *Broadcast from Main Bot:*\n\n{message}",
                    parse_mode='Markdown'
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
        
        await update.message.reply_text(
            f"📢 *Broadcast Sent!*\n\n"
            f"• Message ID: {broadcast_id}\n"
            f"• Sent to: {sent_count} clone bots\n"
            f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode='Markdown'
        )
        
        await self.log_action(update, f"Admin broadcast sent to {sent_count} clones")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ *Admin only command!*", parse_mode='Markdown')
            return
        
        clones = self.db.get_clones()
        active_clones = len(self.clone_bots)
        
        stats_text = (
            "📊 *Bot Statistics*\n\n"
            f"• Total Clones: {len(clones)}\n"
            f"• Active Clones: {active_clones}\n"
            f"• Available Ports: {len(PORTS)}\n"
            f"• Admin ID: {ADMIN_ID}\n"
            f"• Required Channels: {len(REQUIRED_CHANNELS)}\n"
            f"• Services: Phone + Aadhar Lookup\n"
            f"• Flask Port: 8080\n\n"
            "🔄 *System Status:* ✅ Operational"
        )
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def port_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /port command to get available port"""
        user_id = update.effective_user.id
        
        if not await self.is_member(user_id, context):
            await self.send_membership_required_message(update, context)
            return
        
        port = random.choice(PORTS)
        
        await update.message.reply_text(
            f"🔌 *Available Port:*\n\n"
            f"`{port}`\n\n"
            f"*Total ports available:* {len(PORTS)}\n"
            f"*Flask running on:* Port 8080",
            parse_mode='Markdown'
        )

    async def fetch_phone_data(self, phone_number: str):
        """Fetch phone data from the API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{API_URL}{phone_number}") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    else:
                        return None
        except Exception as e:
            logger.error(f"Phone API Error: {e}")
            return None

    async def fetch_aadhar_data(self, aadhaar_number: str):
        """Fetch Aadhar family data from the API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{AADHAR_API_URL}?aadhaar={aadhaar_number}&key={AADHAR_API_KEY}",
                    timeout=30
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    else:
                        return None
        except Exception as e:
            logger.error(f"Aadhar API Error: {e}")
            return None

    def format_phone_data(self, data: dict) -> str:
        """Format the phone data into a stylish message"""
        if not data.get('success') or not data.get('result'):
            return "❌ *No data found for this phone number.*"
        
        result = data['result'][0]
        
        # Stylish formatting with emojis and sections
        message = "📋 *PHONE NUMBER REPORT* 📋\n\n"
        message += "🔍 *Basic Information*\n"
        message += "┌─────────────────────────────\n"
        message += f"│ 📱 *Number:* `{result.get('mobile', 'N/A')}`\n"
        message += f"│ 👤 *Name:* {result.get('name', 'N/A')}\n"
        message += f"│ 👨‍👦 *Father:* {result.get('father_name', 'N/A')}\n"
        message += "└─────────────────────────────\n\n"
        
        message += "🏢 *Service Details*\n"
        message += "┌─────────────────────────────\n"
        message += f"│ 📡 *Circle:* {result.get('circle', 'N/A')}\n"
        message += f"│ 🆔 *ID Number:* {result.get('id_number', 'N/A')}\n"
        message += "└─────────────────────────────\n\n"
        
        # Format address beautifully
        address = result.get('address', '')
        if address and address != 'N/A':
            address_parts = [part for part in address.split('!') if part and part != 'NA!']
            if address_parts:
                message += "🏠 *Address Information*\n"
                message += "┌─────────────────────────────\n"
                for i, part in enumerate(address_parts):
                    message += f"│ 📍 {part}\n"
                message += "└─────────────────────────────\n\n"
        
        # Additional information
        message += "📞 *Contact Details*\n"
        message += "┌─────────────────────────────\n"
        message += f"│ 📞 *Alt Mobile:* {result.get('alt_mobile', 'N/A')}\n"
        message += f"│ 📧 *Email:* {result.get('email', 'N/A')}\n"
        message += "└─────────────────────────────\n\n"
        
        message += "🔗 *Data Source:* @revangeosint\n"
        message += f"⏰ *Generated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return message

    def format_aadhar_data(self, data: dict) -> str:
        """Format Aadhar family data into a stylish message"""
        if not data or 'error' in data:
            return "❌ *No family data found for this Aadhar number.*"
        
        # Stylish formatting for Aadhar data
        message = "👨‍👩‍👧‍👦 *AADHAR FAMILY REPORT* 👨‍👩‍👧‍👦\n\n"
        
        # Basic Information
        message += "🏠 *Family Information*\n"
        message += "┌─────────────────────────────\n"
        message += f"│ 🆔 *RC ID:* {data.get('rcId', 'N/A')}\n"
        message += f"│ 🏠 *Scheme:* {data.get('schemeName', 'N/A')}\n"
        message += f"│ 📍 *District:* {data.get('homeDistName', 'N/A')}\n"
        message += f"│ 🏛️ *State:* {data.get('homeStateName', 'N/A')}\n"
        message += "└─────────────────────────────\n\n"
        
        # Address
        address = data.get('address', '')
        if address:
            message += "📍 *Family Address*\n"
            message += "┌─────────────────────────────\n"
            message += f"│ {address}\n"
            message += "└─────────────────────────────\n\n"
        
        # Family Members
        members = data.get('memberDetailsList', [])
        if members:
            message += f"👥 *Family Members ({len(members)})*\n"
            message += "┌─────────────────────────────\n"
            for member in members:
                relation_emoji = "👤"  # Default
                relation = member.get('releationship_name', '')
                if relation == 'SELF':
                    relation_emoji = "👑"
                elif relation in ['WIFE', 'HUSBAND']:
                    relation_emoji = "💑"
                elif relation == 'SON':
                    relation_emoji = "👦"
                elif relation == 'DAUGHTER':
                    relation_emoji = "👧"
                elif relation == 'FATHER':
                    relation_emoji = "👨"
                elif relation == 'MOTHER':
                    relation_emoji = "👩"
                
                message += f"│ {relation_emoji} *{member.get('memberName', 'N/A')}*\n"
                message += f"│   └─ {relation} ({member.get('memberId', 'N/A')})\n"
            message += "└─────────────────────────────\n\n"
        
        # Additional Details
        message += "📊 *Additional Details*\n"
        message += "┌─────────────────────────────\n"
        message += f"│ ✅ *UID Status:* {data.get('dup_uid_status', 'N/A')}\n"
        message += f"│ ✅ *ONORC Allowed:* {data.get('allowed_onorc', 'N/A')}\n"
        message += f"│ 🆔 *FPS ID:* {data.get('fpsId', 'N/A')}\n"
        message += "└─────────────────────────────\n\n"
        
        message += "🔗 *Data Source:* @revangeosint\n"
        message += f"⏰ *Generated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return message

    async def handle_user_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle both phone numbers and aadhar numbers automatically"""
        user_id = update.effective_user.id
        
        # Check membership first
        if not await self.is_member(user_id, context):
            await self.send_membership_required_message(update, context)
            return
        
        user_input = update.message.text.strip()
        
        # Auto-detect input type
        if user_input.isdigit():
            if len(user_input) == 10:
                # Phone number lookup
                await self.process_phone_lookup(update, context, user_input)
            elif len(user_input) == 12:
                # Aadhar lookup
                await self.process_aadhar_lookup(update, context, user_input)
            else:
                await update.message.reply_text(
                    "❌ *Invalid input!*\n\n"
                    "Please send:\n"
                    "• 10-digit phone number\n"
                    "• 12-digit Aadhar number\n\n"
                    "Or use:\n"
                    "`/aadhar 658014451208`",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Please send only numbers!*\n\n"
                "📱 *Phone Lookup:* 10 digits\n"
                "🆔 *Aadhar Lookup:* 12 digits",
                parse_mode='Markdown'
            )

    async def process_phone_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone_number: str):
        """Process phone number lookup"""
        user_id = update.effective_user.id
        
        # Send stylish processing message
        processing_msg = await update.message.reply_text(
            "📱 *Phone Lookup in Progress...*\n\n"
            "▰▰▰▰▰▰▰▰▰▰ 0%",
            parse_mode='Markdown'
        )
        
        try:
            # Simulate progress
            for i in range(1, 6):
                await asyncio.sleep(0.5)
                progress = i * 20
                bars = "▰" * i + "▱" * (5 - i)
                await processing_msg.edit_text(
                    f"📱 *Phone Lookup in Progress...*\n\n"
                    f"{bars} {progress}%",
                    parse_mode='Markdown'
                )
            
            # Fetch data from API
            data = await self.fetch_phone_data(phone_number)
            
            # Delete processing message
            await processing_msg.delete()
            
            if data:
                # Format and send the result
                formatted_message = self.format_phone_data(data)
                await update.message.reply_text(formatted_message, parse_mode='Markdown')
                
                # Log the lookup
                await self.log_action(update, f"MAIN - User {user_id} looked up phone: {phone_number}")
            else:
                await update.message.reply_text("❌ *Error fetching phone data. Please try again later.*", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error processing phone number: {e}")
            # Delete processing message on error
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text("❌ *An error occurred while processing your request.*", parse_mode='Markdown')

    async def process_aadhar_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, aadhaar_number: str):
        """Process Aadhar family lookup"""
        user_id = update.effective_user.id
        
        # Send stylish processing message
        processing_msg = await update.message.reply_text(
            "🆔 *Aadhar Family Lookup in Progress...*\n\n"
            "▰▰▰▰▰▰▰▰▰▰ 0%",
            parse_mode='Markdown'
        )
        
        try:
            # Simulate progress
            for i in range(1, 6):
                await asyncio.sleep(0.5)
                progress = i * 20
                bars = "▰" * i + "▱" * (5 - i)
                await processing_msg.edit_text(
                    f"🆔 *Aadhar Family Lookup in Progress...*\n\n"
                    f"{bars} {progress}%",
                    parse_mode='Markdown'
                )
            
            # Fetch data from API
            data = await self.fetch_aadhar_data(aadhaar_number)
            
            # Delete processing message
            await processing_msg.delete()
            
            if data:
                # Format and send the result
                formatted_message = self.format_aadhar_data(data)
                await update.message.reply_text(formatted_message, parse_mode='Markdown')
                
                # Log the lookup
                await self.log_action(update, f"MAIN - User {user_id} looked up Aadhar: {aadhaar_number}")
            else:
                await update.message.reply_text("❌ *Error fetching Aadhar data. Please try again later.*", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error processing Aadhar number: {e}")
            # Delete processing message on error
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text("❌ *An error occurred while processing your Aadhar request.*", parse_mode='Markdown')

    async def log_action(self, update: Update, action: str):
        """Log actions to admin"""
        try:
            user_id = update.effective_user.id if update.effective_user else 'N/A'
            log_message = (
                f"📝 *Bot Log*\n\n"
                f"• Action: {action}\n"
                f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• User: {user_id}"
            )
            await self.application.bot.send_message(chat_id=ADMIN_ID, text=log_message, parse_mode='Markdown')
            
            # Also log to database
            self.db.log_activity(user_id, action)
        except Exception as e:
            logger.error(f"Logging error: {e}")

    def run(self):
        """Start the bot and Flask server"""
        logger.info("🤖 Main Bot Starting...")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"📢 Required Channels: {REQUIRED_CHANNELS}")
        logger.info(f"🔌 Available Ports: {len(PORTS)}")
        logger.info(f"🌐 Flask Server on Port: 8080")
        logger.info(f"📱 Services: Phone Lookup + Aadhar Family Info")
        
        # Start Flask server in separate thread
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("✅ Flask server started on port 8080")
        
        # Start existing clones from database
        clones = self.db.get_clones()
        for clone in clones:
            user_id, clone_token, clone_name = clone[1], clone[2], clone[3]
            logger.info(f"🔄 Starting existing clone: {clone_name}")
            # Start with delay to avoid conflicts
            threading.Timer(5, self.clone_manager.start_clone_bot, args=[clone_token, user_id, clone_name]).start()
        
        # Start main bot
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False
        )

if __name__ == "__main__":
    bot = PhoneLookupBot()
    bot.run()
