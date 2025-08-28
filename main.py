import telebot  

BOT_TOKEN = "8208913505:AAGVd4_RiC3wG2MtpGkiO64G-Sn5sVOazJM"

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я эхо-бот. Напиши что-нибудь.")

@bot.message_handler(content_types=['text'])
def echo(message):
    bot.send_message(message.chat.id, message.text)

print("бот запущен")
bot.polling()
