from telegram.ext import *
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
import telegram
import requests
from openai import OpenAI
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import db
import stripe
from io import BytesIO
from flask import Flask, request
from flask_cors import CORS
import os
import time

app = Flask(__name__)
CORS(app)

firebase_config = {
  "type": "...",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "...",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "...",
  "token_uri": "...",
  "auth_provider_x509_cert_url": "...",
  "client_x509_cert_url": "...",
  "universe_domain": "..."
}

cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred)
db = firestore.client()
PAYMENT_ACTION = 1
CLONE_VOICE_ACTION = 0
PAYMENT_PROVIDER_TOKEN = "..."
TELEGRAM_TOKEN = "..."
client = OpenAI(api_key="...")
stripe.api_key = '...'
updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dp = updater.dispatcher
user_character_balances = 100
#########################           COMMANDS            ##########################
# standart commands
def start_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    existing_data = user_data_interact.get().to_dict()
    global user_data
    if existing_data:
        user_data = existing_data
        context.bot.send_message(chat_id, (f'Welcome back!'))
    else:
        # If no existing data, initialize new user data
        thread = client.beta.threads.create() 
        user_data = {     
            'chat_id': [chat_id, thread.id],
            'output_message': ["speech", "speech"],
            'current_personality': ['nerd', 'assistant_id'],
            'current_voice': "nova",            
            'character_balance': user_character_balances,     
        }    
     
        # Add user data to Firestore
        db.collection('users').document(str(chat_id)).set(user_data)
        context.bot.send_message(chat_id, 'Welcome to gikbot!')

def help_command(update, context):
    chat_id = update.message.chat_id
    context.bot.send_message(chat_id, "<b>How does this bot works?</b>\nYou can use this bot if you have enough character balance. You will get 100 free characters when you first start this bot.\n\n<b>What is a character?</b>\nOne character can be any letter, symbol or space. For example this sentence:\n(I'm a character. = 16 character)\n\n<b>How is character balance deducted?</b>\nFor text and speech output:\nYour character balance will be deducted only for output characters.\n\nFor image and vision output:\n1 image generation = 1000 character\n1 vision response = 1000 character\n\n<b>I have other questions. How can I contact?</b>\ngikman0839@gmail.com", disable_web_page_preview=True, parse_mode=telegram.ParseMode.HTML)

def error(update, context):
    print(f'Update {update} caused error {context.error}')

# payment
def payment_command(update, context):
    chat_id = update.message.chat_id
    payment_keyboard = [[InlineKeyboardButton("1 USD", callback_data="payment_1"), InlineKeyboardButton("5 USD", callback_data="payment_5")]]
    # Add CallbackQueryHandlers with explicit patterns
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_1$'))
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_5$'))
    context.bot.send_message(chat_id, "<b>Stripe</b>\nChoose any amount.\nAfter each purchase,\nchat history will reset", reply_markup=InlineKeyboardMarkup(payment_keyboard), parse_mode=telegram.ParseMode.HTML)

def payment_button_click(update, context):
    query = update.callback_query    
    button_text = query.data    
    query.answer()
    send_invoice(update, context, button_text)

def send_invoice(update, context, button_text):
    """Sends an invoice without shipping-payment."""
    chat_id = update.callback_query.message.chat_id
    # Extract the numeric value from the button text
    numeric_value = int(button_text.split("_")[1])
    title = "Payment"
    description = f"{numeric_value * 2000} characters"
    payload = "Custom-Payload"
    currency = "USD"
    # Dynamically set the price based on the button text
    price = numeric_value
    prices = [LabeledPrice("CONTINUE", price * 100)]
    context.bot.send_invoice(chat_id, title, description, payload, PAYMENT_PROVIDER_TOKEN, currency, prices)
    # Delete the entire message after sending the invoice
    context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)    

def pre_checkout_query(update, context):
    """Answers the PreCheckoutQuery"""
    query = update.pre_checkout_query
    if query.invoice_payload != "Custom-Payload":
        query.answer(ok=False, error_message="Something went wrong...")
    else:
        query.answer(ok=True)        

def successful_payment(update, context):
    """Confirms the successful payment and updates Firebase."""
    chat_id = update.message.chat_id
    payment = update.message.successful_payment
    if payment:
        total_amount = update.message.successful_payment.total_amount
        new_characters = total_amount * 20
        user_data_interact = db.collection('users').document(str(chat_id))
        character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')          
        user_data_interact.update({'character_balance': character_balance + new_characters})                
        new_thread_for_personality(chat_id=chat_id, context=context, update=update)  
    else:
        print("No successful payment information in the update.")    

# other
def change_personality_command(update, context):
    chat_id = update.message.chat_id
    change_voice_keyboard = [
        [InlineKeyboardButton("nerd", callback_data="nerdbot"), InlineKeyboardButton("romantic", callback_data="romanticbot")],
        [InlineKeyboardButton("funny", callback_data="funnybot"), InlineKeyboardButton("serious", callback_data="seriousbot")]
    ]    
    dp.add_handler(CallbackQueryHandler(change_personality_button, pattern='^nerdbot$'))
    dp.add_handler(CallbackQueryHandler(change_personality_button, pattern='^romanticbot$'))
    dp.add_handler(CallbackQueryHandler(change_personality_button, pattern='^funnybot$'))
    dp.add_handler(CallbackQueryHandler(change_personality_button, pattern='^seriousbot$'))
    context.bot.send_message(chat_id=chat_id, text="When you change personality, your chat history will be reset.", reply_markup=InlineKeyboardMarkup(change_voice_keyboard))

def new_thread_for_personality(chat_id, context, update):
    user_data_interact = db.collection('users').document(str(chat_id))
    thread = user_data_interact.get(['chat_id']).to_dict().get('chat_id') 
    try:
        client.beta.threads.delete(thread_id=thread[1])   
    except:
        pass
    new_thread = client.beta.threads.create()
    user_data_interact.update({'chat_id': [chat_id, new_thread.id]})
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    except:
        pass

def change_personality_button(update, context):
    chat_id = update.callback_query.message.chat_id
    query = update.callback_query
    query.answer()
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
    voice_button = query.data
    if voice_button == "nerdbot":
        user_data_interact.update({'current_personality': ['nerd', 'assistant_id']})
        if character_balance != 0:
            new_thread_for_personality(chat_id=chat_id, context=context, update=update)
        context.bot.send_message(chat_id=chat_id, text='Personality updated.')
    elif voice_button == "romanticbot":
        user_data_interact.update({'current_personality': ['romantic', 'assistant_id']})
        if character_balance != 0:
            new_thread_for_personality(chat_id=chat_id, context=context, update=update)
        context.bot.send_message(chat_id=chat_id, text='Personality updated.')
    elif voice_button == "funnybot":
        user_data_interact.update({'current_personality': ['funny', 'assistant_id']})
        if character_balance != 0:
            new_thread_for_personality(chat_id=chat_id, context=context, update=update)
        context.bot.send_message(chat_id=chat_id, text='Personality updated.')
    elif voice_button == "seriousbot":
        user_data_interact.update({'current_personality': ['serious', 'assistant_id']})
        if character_balance != 0:
            new_thread_for_personality(chat_id=chat_id, context=context, update=update)
        context.bot.send_message(chat_id=chat_id, text='Personality updated.')

def change_voice_command(update, context):
    chat_id = update.message.chat_id
    change_voice_keyboard = [
        [InlineKeyboardButton("Alloy", callback_data="alloy"), InlineKeyboardButton("Echo", callback_data="echo"), InlineKeyboardButton("Fable", callback_data="fable")],
        [InlineKeyboardButton("Onyx", callback_data="onyx"), InlineKeyboardButton("Nova", callback_data="nova"), InlineKeyboardButton("Shimmer", callback_data="shimmer")]
    ]    
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^alloy$'))
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^echo$'))
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^fable$'))
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^onyx$'))
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^nova$'))
    dp.add_handler(CallbackQueryHandler(change_voice_button, pattern='^shimmer$'))
    context.bot.send_message(chat_id=chat_id, text="Choose AI-generated voice.", reply_markup=InlineKeyboardMarkup(change_voice_keyboard))

def change_voice_button(update, context):
    chat_id = update.callback_query.message.chat_id
    query = update.callback_query
    query.answer()
    user_data_interact = db.collection('users').document(str(chat_id))
    voice_button = query.data
    if voice_button == "alloy":
        user_data_interact.update({'current_voice': "alloy"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    elif voice_button == "echo":
        user_data_interact.update({'current_voice': "echo"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    elif voice_button == "fable":
        user_data_interact.update({'current_voice': "fable"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    elif voice_button == "onyx":
        user_data_interact.update({'current_voice': "onyx"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    elif voice_button == "nova":
        user_data_interact.update({'current_voice': "nova"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
    elif voice_button == "shimmer":
        user_data_interact.update({'current_voice': "shimmer"})
        context.bot.send_message(chat_id=chat_id, text='Current voice updated.')
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)

def my_profile_command(update, context):
        chat_id = update.message.chat_id
        user_data_interact = db.collection('users').document(str(chat_id))
        existing_data = user_data_interact.get().to_dict()
        character_balance = existing_data.get('character_balance')
        current_voice = existing_data.get('current_voice')
        current_personality = existing_data.get('current_personality')
        output_message = existing_data.get('output_message')
        if existing_data:
            context.bot.send_message(chat_id, f"<b>character balance:</b> {character_balance}\n<b>current voice:</b> {current_voice}\n<b>current personality:</b> {current_personality[0]}\n<b>output message:</b> {output_message[0]}\n<b>chat id:</b> {chat_id}", parse_mode=telegram.ParseMode.HTML)
        else:
            context.bot.send_message(chat_id, "Unable to retrieve user data.")

def output_text_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    context.bot.send_message(chat_id, f"<b>GPT3.5</b>\nOutput messages are now only generated text. Multilingual supported.\n\nOnly output characters will be deducted from the character balance.", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': ["text", "text"]})

def output_speech_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    context.bot.send_message(chat_id, f"<b>GPT3.5 + OpenAI TTS</b>\nOutput messages are now only generated speech. Multilingual supported.\n\nOnly output characters will be deducted from the character balance.", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': ["speech", "speech"]})

def output_image_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    output_message = user_data_interact.get(['output_message']).to_dict().get('output_message')
    context.bot.send_message(chat_id, f"<b>DALL·E 3</b>\nOutput messages are now only generated images. Send a text or voice message to describe what you want to generate.\n\n💰1 image = 1000 characters💰", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': ["image", output_message[1]]})

def output_vision_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    output_message = user_data_interact.get(['output_message']).to_dict().get('output_message')
    context.bot.send_message(chat_id, f"<b>GPT4 Vision</b>\nOutput messages are now only vision response. Send one photo with or without a text caption. If you receive a text response, select the outputspeech command before this command, and you will receive a voice response.\n\n💰1 response = 1000 characters💰", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': ["vision", output_message[1]]})

def whisper_transcribe(chat_id, url, format):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')

    if character_balance > 10:
        response = requests.get(url)
        transcript = client.audio.transcriptions.create(
        model="whisper-1", 
        file=("name", response.content, format),
        response_format="text"     
        )

    elif character_balance <= 10:
        user_data_interact.update({'character_balance': 0})

    return transcript

def openai_voice(current_voice, chatgpt_message):
    response = client.audio.speech.create(model="tts-1", voice=current_voice, input=chatgpt_message)
    return response.content

def dalle_image(chat_id, text_message, update, context):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
    if character_balance >= 1000:
        update.message.reply_text("Generating image. Please wait a few seconds...")
        response_dalle = client.images.generate(model="dall-e-3", prompt=text_message, size="1024x1024", quality="standard", n=1,)
        image_url = response_dalle.data[0].url 
        user_data_interact.update({'character_balance': character_balance - 1000})
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO)          
    elif character_balance < 1000:
        pass
    return image_url          
    
def chatgpt_vision(chat_id, text_message, image_url, update):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
    if character_balance >= 1000:
        update.message.reply_text("Generating response. Please wait a few seconds...")
        response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=[{"role": "user", "content": [{"type": "text", "text": text_message},{"type": "image_url", "image_url": {"url": image_url,},},],}],max_tokens=300,
    )
        user_data_interact.update({'character_balance': character_balance - 1000})
    elif character_balance < 1000:
        pass
    return response.choices[0].message.content

def unknown_command_handler(update, context):
    chat_id = update.message.chat_id
    text_message = update.message.text
    text_message_split = str(text_message).split()
    command_list = ['/start', '/help', '/myprofile', '/payment', '/output', '/changevoice', '/clonevoice']
    if text_message_split[0].startswith("/") and text_message_split[0] not in command_list:
        context.bot.send_message(chat_id, "Please provide the correct command.")

# assistant
def wait_on_run(run, thread, chat_id):
    while run.status == "queued" or run.status == "in_progress":
        user_data_interact = db.collection('users').document(str(chat_id))
        character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
        run = client.beta.threads.runs.retrieve(thread_id=thread, run_id=run.id)        
        if character_balance < 10:
            break
        time.sleep(0.5)
    return run
        
def chatgpt_assistant(chat_id, text_message, context):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
    current_personality = user_data_interact.get(['current_personality']).to_dict().get('current_personality')
    thread = user_data_interact.get(['chat_id']).to_dict().get('chat_id')     
    if character_balance >= 10:
        message = client.beta.threads.messages.create(thread_id=thread[1], role="user", content=text_message)
        run = client.beta.threads.runs.create(thread_id=thread[1], assistant_id=current_personality[1])
        run = wait_on_run(run, thread[1], chat_id=chat_id)
        # Retrieve all the messages added after our last user message        
        messages = client.beta.threads.messages.list(thread_id=thread[1], order="asc", after=message.id)
        chatgpt_message = messages.data[0].content[0].text.value    

        character_count = len(chatgpt_message)           
        user_data_interact.update({'character_balance': character_balance - character_count})
        character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
        if character_balance < 10:
            user_data_interact.update({'character_balance': 0})
    elif character_balance < 10:
        user_data_interact.update({'character_balance': 0})

    return chatgpt_message

def output_text(update, context, chat_id, voice_message, text_message, document_message, audio_message, photo_message, video_message):
    if voice_message is not None:
        voice_format = update.message.voice.mime_type
        file_id = update.message.voice.file_id
        url = context.bot.get_file(file_id).file_path    
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)            
        transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
        chatgpt_message = chatgpt_assistant(chat_id=chat_id, text_message=transcript, context=context)   
        context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
    elif text_message is not None:
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
        chatgpt_message = chatgpt_assistant(chat_id=chat_id, text_message=text_message, context=context) 
        context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
    elif document_message is not None or audio_message is not None or photo_message is not None or video_message is not None:
        context.bot.send_message(chat_id=chat_id, text="Can't process this data at the moment.") 

def output_speech(update, context, chat_id, voice_message, text_message, document_message, audio_message, photo_message, video_message, current_voice):
    if voice_message is not None:
        voice_format = update.message.voice.mime_type
        file_id = update.message.voice.file_id
        url = context.bot.get_file(file_id).file_path    
        transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
        chatgpt_message = chatgpt_assistant(chat_id=chat_id, text_message=transcript, context=context)
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
        openai_tts = openai_voice(current_voice=current_voice, chatgpt_message=chatgpt_message)
        context.bot.send_voice(chat_id=chat_id, voice=openai_tts)
    elif text_message is not None:
        chatgpt_message = chatgpt_assistant(chat_id=chat_id, text_message=text_message, context=context) 
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
        openai_tts = openai_voice(current_voice=current_voice, chatgpt_message=chatgpt_message)
        context.bot.send_voice(chat_id=chat_id, voice=openai_tts)   
    elif document_message is not None or audio_message is not None or photo_message is not None or video_message is not None:
        context.bot.send_message(chat_id=chat_id, text="Can't process this data at the moment.")  

def output_image(update, context, chat_id, voice_message, text_message, document_message, audio_message, photo_message, video_message):
    if voice_message is not None:
        voice_format = update.message.voice.mime_type
        file_id = update.message.voice.file_id
        url = context.bot.get_file(file_id).file_path    
        transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
        dalle_url = dalle_image(chat_id=chat_id, text_message=transcript, update=update, context=context)
        response = requests.get(dalle_url)
        context.bot.send_photo(chat_id=chat_id, photo=response.content)
    elif text_message is not None:
        dalle_url = dalle_image(chat_id=chat_id, text_message=text_message, update=update, context=context)
        response = requests.get(dalle_url)
        context.bot.send_photo(chat_id=chat_id, photo=response.content)  
    elif document_message is not None or audio_message is not None or photo_message is not None or video_message is not None:
        context.bot.send_message(chat_id=chat_id, text="This data is not acceptable. Send a text or voice message to describe what you want to generate")          

def output_vision(update, context, chat_id, voice_message, text_message, document_message, audio_message, photo_message, video_message, output_message, current_voice):
    if text_message is not None or voice_message is not None or audio_message is not None or video_message is not None:
        context.bot.send_message(chat_id=chat_id, text="Please send one photo with or without a text caption. Supported formats:\npng, jpeg, jpg and webp")

    try:
        if photo_message is not None:
            caption = update.message.caption
            file_id = update.message.photo[-1].get_file()
            url = context.bot.get_file(file_id).file_path
            if caption is None:
                caption = "What’s in this image?"
            chatgpt_v = chatgpt_vision(chat_id=chat_id, text_message=caption, image_url=url, update=update)
            if output_message[1] == "speech":   
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
                openai_tts = openai_voice(current_voice=current_voice, chatgpt_message=chatgpt_v)
                context.bot.send_voice(chat_id=chat_id, voice=openai_tts)
            elif output_message[1] == "text":
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
                context.bot.send_message(chat_id=chat_id, text=chatgpt_v)
    except:
        if document_message is not None:
            file_id = update.message.document.file_id
            url = context.bot.get_file(file_id).file_path
            format_name = url.split('.')[-1]
            if format_name in ["jpeg", "jpg", "png", "webp"]:
                caption = update.message.caption
                if caption is None:
                    caption = "What’s in this image?"
                chatgpt_v = chatgpt_vision(chat_id=chat_id, text_message=caption, image_url=url, update=update)
                if output_message[1] == "speech":
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
                    openai_tts = openai_voice(current_voice=current_voice, chatgpt_message=chatgpt_v)
                    context.bot.send_voice(chat_id=chat_id, voice=openai_tts)   
                elif output_message[1] == "text":
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
                    context.bot.send_message(chat_id=chat_id, text=chatgpt_v)

#########################           HANDLES           ##########################
def handle_message(update, context):
    chat_id = update.message.chat_id
    text_message = update.message.text
    voice_message = update.message.voice  
    document_message = update.message.document
    audio_message = update.message.audio
    photo_message = update.message.photo    
    video_message = update.message.video
    user_data_interact = db.collection('users').document(str(chat_id))
    output_message = user_data_interact.get(['output_message']).to_dict().get('output_message')
    current_voice = user_data_interact.get(['current_voice']).to_dict().get('current_voice')
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')
        
    if output_message[0] == 'text' and character_balance > 0:
        try:
            output_text(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message)
        except:
            try:
                time.sleep(1)
                output_text(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message)
            except:
                context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")

    elif output_message[0] == 'speech' and character_balance > 0:
        try:
            output_speech(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message, current_voice=current_voice)
        except:
            try:
                time.sleep(1)
                output_speech(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message, current_voice=current_voice)
            except:
                context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")

    elif output_message[0] == 'image' and character_balance >= 1000:
        try:
            output_image(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message)
        except:
            try:
                time.sleep(1)
                output_image(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message)
            except:
                context.bot.send_message(chat_id=chat_id, text="You don't have enough character balance. If you still have characters, there might be technical difficulties.")     

    elif output_message[0] == 'vision' and character_balance >= 1000:
        try:
            output_vision(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message, output_message=output_message, current_voice=current_voice)
        except:
            try:
                time.sleep(1)
                output_vision(update=update, context=context, chat_id=chat_id, voice_message=voice_message, text_message=text_message, document_message=document_message, audio_message=audio_message, photo_message=photo_message, video_message=video_message, output_message=output_message, current_voice=current_voice)
            except:
                context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")

    elif character_balance < 0:
        user_data_interact.update({'character_balance': 0})
        context.bot.send_message(chat_id=chat_id, text="You don't have enough character balance. If you still have characters, there might be technical difficulties.")

    else:
        context.bot.send_message(chat_id=chat_id, text="You don't have enough character balance. If you still have characters, there might be technical difficulties.")

#########################           COMBINING_ALL           ##########################
dp.add_handler(CommandHandler('start', start_command))
dp.add_handler(CommandHandler('help', help_command))
dp.add_handler(CommandHandler('myprofile', my_profile_command))
dp.add_handler(CommandHandler('payment', payment_command))
dp.add_handler(CommandHandler('outputtext', output_text_command))
dp.add_handler(CommandHandler('outputspeech', output_speech_command))
dp.add_handler(CommandHandler('outputimage', output_image_command))
dp.add_handler(CommandHandler('outputvision', output_vision_command))
dp.add_handler(CommandHandler('changevoice', change_voice_command))
dp.add_handler(CommandHandler('changepersonality', change_personality_command))
dp.add_handler(CommandHandler("invoice", send_invoice))
dp.add_handler(PreCheckoutQueryHandler(pre_checkout_query))
dp.add_handler(MessageHandler(Filters.successful_payment, successful_payment))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command | Filters.voice | Filters.document | Filters.audio | Filters.photo | Filters.video, handle_message))
dp.add_handler(MessageHandler(Filters.command, unknown_command_handler))
dp.add_error_handler(error)    

# Endpoint to handle incoming Telegram updates
@app.route(f"/{TELEGRAM_TOKEN}", methods=['POST'])
def telegram_webhook():
    json_data = request.get_json()
    dp.process_update(Update.de_json(json_data, updater.bot))
    return 'telegram working', 200

@app.route("/")
def main():    
    updater.start_webhook(webhook_url="..." + TELEGRAM_TOKEN)
    return "working"

if __name__ == "__main__":
    # Start the Flask app
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
