from telegram.ext import *
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
import telegram
import requests
from elevenlabs import clone, set_api_key
from openai import OpenAI
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import db
import stripe
import tempfile
from flask import Flask, request
from flask_cors import CORS
import os

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
ELVENLABS_TOKEN = "..."
client = OpenAI(api_key="...")
stripe.api_key = '...'
set_api_key(ELVENLABS_TOKEN)
updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dp = updater.dispatcher
user_character_balances = 250
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
        user_data = {
            'payment_for_clone': "no payment",            
            'chat_id': chat_id,
            'output_message': "speech",
            'cloned_voice': "",
            'current_voice': "ELEVENLAB_VOICE_ID",            
            'character_balance': user_character_balances           
        }    
        
        # Add user data to Firestore
        db.collection('users').document(str(chat_id)).set(user_data)
        context.bot.send_message(chat_id, 'Welcome to gikbot!')

def help_command(update, context):
    chat_id = update.message.chat_id

    context.bot.send_message(chat_id, "<b>How does this bot works?</b>\nYou can use this bot if you have enough character balance. You will get 250 free characters when you first start this bot.\nCheck out the video tutorial:\nhttps://youtu.be/HEk-R0KJwgo?t=05m42s\n\n<b>What is a character?</b>\nOne character can be any letter, symbol or space.\nFor example this sentence:\n(I'm a character. = 16 character)\n\n<b>What does the myprofile command do?</b>\nWith this command, you can check how many characters you have left, your current voice_id, any cloned voice you have, output messages from the bot, and your unique chat_id for this bot.\n\n<b>I have other questions. How can I contact?</b>\ngikman0839@gmail.com", disable_web_page_preview=True, parse_mode=telegram.ParseMode.HTML)

def error(update, context):
    print(f'Update {update} caused error {context.error}')

# payment
def payment_command(update, context):
    chat_id = update.message.chat_id

    payment_keyboard = [
        [InlineKeyboardButton("5 USD", callback_data="payment_5"), InlineKeyboardButton("10 USD", callback_data="payment_10"), InlineKeyboardButton("20 USD", callback_data="payment_20")],
        [InlineKeyboardButton("50 USD", callback_data="payment_50"), InlineKeyboardButton("100 USD", callback_data="payment_100")]
    ]

    # Add CallbackQueryHandlers with explicit patterns
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_5$'))
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_10$'))
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_20$'))
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_50$'))
    dp.add_handler(CallbackQueryHandler(payment_button_click, pattern='^payment_100$'))

    context.bot.send_message(chat_id, "\nChoose any amount.\n\n", reply_markup=InlineKeyboardMarkup(payment_keyboard))

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
    description = f"{numeric_value * 1000} characters"
    payload = "Custom-Payload"
    currency = "USD"
    # Dynamically set the price based on the button text
    price = numeric_value
    prices = [LabeledPrice("CONTINUE", price * 100)]
    context.bot.send_invoice(chat_id, title, description, payload, PAYMENT_PROVIDER_TOKEN, currency, prices, need_email=True)
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
        successful_payment_message = update.message.successful_payment
        total_amount = update.message.successful_payment.total_amount
        new_characters = total_amount * 10
        receipt_email = successful_payment_message.order_info.email  # Get the email from order_info
        user_data_interact = db.collection('users').document(str(chat_id))
        payment_for_clone = user_data_interact.get(['payment_for_clone']).to_dict().get('payment_for_clone')  
        character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')          

        if payment_for_clone == "no payment":
            user_data_interact.update({
                'payment_for_clone': "ready to use"
            })       

        user_data_interact.update({
            'character_balance': character_balance + new_characters
        })                

        # Trigger Stripe to send an email receipt
        provider_payment_charge_id = successful_payment_message.provider_payment_charge_id
        charge_object = stripe.Charge.retrieve(provider_payment_charge_id)
        payment_intent_id = charge_object.payment_intent
        stripe.PaymentIntent.modify(payment_intent_id, receipt_email=receipt_email) 
    else:
        print("No successful payment information in the update.")    

# clone voice related
def change_voice_command(update, context):
    chat_id = update.message.chat_id
    text_message = update.message.text
    user_data_interact = db.collection('users').document(str(chat_id))
    text_message_split = str(text_message).split()
    if text_message == "/changevoice":
        context.bot.send_message(chat_id, "To set a new voice, send this command format to the bot:\n(Note: If you provide a non-existing voice_id, you will receive an empty voice message, and your character balance will be deducted for the GPT4 API request before requesting ElevenLabs API, as outputspeech command works with two API requests)\n\n/changevoice <b>voice_id</b>", parse_mode=telegram.ParseMode.HTML)
    elif text_message_split[0] == "/changevoice" and len(text_message_split) == 2:
        context.bot.send_message(chat_id, "If you provided the correct and existing <b>voice_id</b>, the new voice should now be set.", parse_mode=telegram.ParseMode.HTML)
        user_data_interact.update({
            'current_voice': f"{text_message_split[1]}"
        })

def process_and_create_clone_voice(context, chat_id, file_id_list):
    user_data_interact = db.collection('users').document(str(chat_id))
    payment_for_clone = user_data_interact.get(['payment_for_clone']).to_dict().get('payment_for_clone')
    temp_file_path_list = []
    for file_id in file_id_list:
        url = context.bot.get_file(file_id).file_path
        format = url.split('.')[-1]
        response = requests.get(url)
        #Create a temporary file and save the content
        with tempfile.NamedTemporaryFile(delete=False, suffix=format) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        temp_file_path_list.append(temp_file_path)

    # Pass the temporary file path to the clone function
    voice = clone(
        name=f"{chat_id}",
        files=temp_file_path_list
    )

    voice_id = voice.voice_id
    # Update the 'cloned_voice' field with the generated voice_id
    user_data_interact.update({'cloned_voice': voice_id})

    if voice_id and payment_for_clone == "ready to use":
        user_data_interact.update({'payment_for_clone': "used"})

    return voice_id

def receive_audio(update, context):
    chat_id = update.message.chat_id       
    text_message = update.message.text
    audio_message = update.message.audio 
    voice_message = update.message.voice     
    document_message = update.message.document 
    global url_list
    url_list = []       
    global file_id_list
    file_id_list = []
    # Check if 'total_duration' key exists in 'context.user_data', if not, initialize it to 59 seconds
    if 'total_duration' not in context.user_data:
        context.user_data['total_duration'] = 5

    total_duration = context.user_data['total_duration']
    if audio_message is not None:     
        document_message_format = update.message.audio.mime_type
        file_id = update.message.audio.file_id
        file_id_list.append(file_id)
        total_duration = total_duration - 1      
    elif voice_message is not None:
        file_id = update.message.voice.file_id
        file_id_list.append(file_id)
        total_duration = total_duration - 1
    elif document_message is not None:
        try:
            document_message_format = update.message.document.mime_type
            document_message_format_check = document_message_format.split('/')[0]
            if document_message_format_check == 'audio':
                file_id = update.message.document.file_id
                file_id_list.append(file_id)
                total_duration = total_duration - 1
            else:
                update.message.reply_text("Please either provide audio, click the submit button, or click the cancel button to cancel the clone voice command.")
        except:
            update.message.reply_text("Please either provide audio, click the submit button, or click the cancel button to cancel the clone voice command.")
    elif text_message is not None:
        update.message.reply_text("Please either provide audio, click the submit button, or click the cancel button to cancel the clone voice command.")
    else:
        update.message.reply_text("Please either provide audio, click the submit button, or click the cancel button to cancel the clone voice command.")

    # Update 'total_duration' in 'context.user_data' for future reference
    context.user_data['total_duration'] = total_duration

    # Update 'total_duration' in 'context.user_data' for future reference
    if total_duration == -1:
        update.message.reply_text("Command canceled as the total audio files exceed the limit.", reply_markup=ReplyKeyboardRemove())
        context.user_data['total_duration'] = 5
        return ConversationHandler.END
    elif total_duration == 0:
        update.message.reply_text(f"You can click the sumbit button now.") 
    else:
        update.message.reply_text(f"You can upload another {total_duration} audio files. Click the sumbit button when you're ready.")
        return CLONE_VOICE_ACTION

def clone_voice_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    payment_for_clone = user_data_interact.get(['payment_for_clone']).to_dict().get('payment_for_clone')
    if payment_for_clone == "no payment":
        # User didn't make purchase yet
        update.message.reply_text("You can only clone one voice once with a payment, and currently, this bot offers a limited number of new voice cloning. This means that even if you make a payment, the bot may have already reached the limit.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    elif payment_for_clone == "used":
        # User has already cloned their voice
        update.message.reply_text("You can only clone one voice for now, and you have already cloned a voice.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    else:
        keyboard = ReplyKeyboardMarkup([["Submit", "Cancel"]], resize_keyboard=True, one_time_keyboard=True)
        context.bot.send_message(chat_id=update.effective_chat.id, text="For optimal cloning results, provide at least 30 to 60 seconds of diverse, high-quality audio samples covering styles like storytelling, casual talk, and more. Make sure there are pauses and tonal variations.\nSample quality is more important than quantity. Noisy samples may give bad results.\nOne audio file should not exceed 10 MB.\n\nNote: After you submit your audio/audios, this bot may have already reached clone voice limit. You can only clone one voice, and you can delete it afterward, but you can't create a new one for now.", reply_markup=keyboard)

    return CLONE_VOICE_ACTION

def clone_button_click(update, context):
    chat_id = update.message.chat_id
    button_text = update.message.text
    if button_text == 'Submit':
        update.message.reply_text("If you provided all the audio files, please wait a few seconds...")
        # Clone voice
        voice_id = process_and_create_clone_voice(context=context, chat_id=chat_id, file_id_list=file_id_list)
        if voice_id:
            context.bot.send_message(chat_id=chat_id, text=f"<b>voice_id</b>: {voice_id}\n\nTo set this voice, send this command format to the bot:\n/changevoice {voice_id}", parse_mode=telegram.ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
            context.user_data['total_duration'] = 5
            return ConversationHandler.END         
        else:
            context.bot.send_message(chat_id=chat_id, text="Something went wrong. Try using a different audio format.")
    elif button_text == 'Cancel':
        context.bot.send_message(chat_id=chat_id, text="Command canceled.", reply_markup=ReplyKeyboardRemove(selective=True, timeout=1))
        context.user_data['total_duration'] = 5
        return ConversationHandler.END
    else:     
        update.message.reply_text("Please either provide audio, click the submit button, or click the cancel button to cancel the clone voice command.")
    # Assuming the user provided additional audio
    return CLONE_VOICE_ACTION

def delete_clone_voice_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    cloned_voice_id = user_data_interact.get(['cloned_voice']).to_dict().get('cloned_voice')
    delete_voice_keyboard = [[InlineKeyboardButton("Yes", callback_data="yesdelete"), InlineKeyboardButton("No", callback_data="nostop")]]    
    dp.add_handler(CallbackQueryHandler(delete_clone_voice_button_click, pattern='^yesdelete$'))
    dp.add_handler(CallbackQueryHandler(delete_clone_voice_button_click, pattern='^nostop$'))
    if cloned_voice_id != "":
        context.bot.send_message(chat_id, "After deleting your cloned voice, it can't be restored and you can't create a new one for now. Delete it anyway?", reply_markup=InlineKeyboardMarkup(delete_voice_keyboard))
    elif cloned_voice_id == "":
        context.bot.send_message(chat_id, "You haven't cloned a new voice yet, or you already deleted the cloned voice.")

def delete_clone_voice_button_click(update, context):
    chat_id = update.callback_query.message.chat_id
    query = update.callback_query
    query.answer()
    user_data_interact = db.collection('users').document(str(chat_id))
    cloned_voice_id = user_data_interact.get(['cloned_voice']).to_dict().get('cloned_voice')
    current_voice_id = user_data_interact.get(['current_voice']).to_dict().get('current_voice')
    yes_button = query.data
    if yes_button == "yesdelete":
        url = "https://api.elevenlabs.io/v1/voices/{}".format(cloned_voice_id)
        headers = {"xi-api-key": ELVENLABS_TOKEN}
        response = requests.delete(url, headers=headers)
        if response.status_code == 200 and cloned_voice_id != current_voice_id:
            user_data_interact.update({'cloned_voice': ""})
            context.bot.send_message(chat_id=chat_id, text='You deleted your cloned voice.')
            context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
        elif response.status_code == 200 and cloned_voice_id == current_voice_id:
            user_data_interact.update({'cloned_voice': ""})
            user_data_interact.update({'current_voice': ""})
            context.bot.send_message(chat_id=chat_id, text='You deleted your cloned voice.')
            context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)
        else:
            context.bot.send_message(chat_id, "Something went wrong.")
    elif yes_button == "nostop":
        context.bot.send_message(chat_id=chat_id, text="Command canceled.")
        context.bot.delete_message(chat_id=chat_id, message_id=update.callback_query.message.message_id)

def voice_library_command(update, context):
    update.message.reply_text("<b>Marcus:</b> ELEVENLAB_VOICE_ID\n\n<b>Joanne:</b> ELEVENLAB_VOICE_ID\n\n<b>Alex:</b> ELEVENLAB_VOICE_ID\n\n<b>Natasha:</b> ELEVENLAB_VOICE_ID", parse_mode=telegram.ParseMode.HTML)

# other
def my_profile_command(update, context):
        chat_id = update.message.chat_id
        user_data_interact = db.collection('users').document(str(chat_id))
        existing_data = user_data_interact.get().to_dict()
        character_balance = existing_data.get('character_balance')
        current_voice = existing_data.get('current_voice')
        cloned_voice = existing_data.get('cloned_voice')
        output_message = existing_data.get('output_message')

        if existing_data:
            context.bot.send_message(chat_id, f"<b>character balance:</b> {character_balance}\n<b>current voice:</b> {current_voice}\n<b>cloned voice:</b> {cloned_voice}\n<b>output message:</b> {output_message}\n<b>chat id:</b> {chat_id}", parse_mode=telegram.ParseMode.HTML)
        else:
            context.bot.send_message(chat_id, "Unable to retrieve user data.")

def output_text_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    context.bot.send_message(chat_id, f"<b>GPT4</b>\nOutput messages are now only generated text.", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': "text"})

def output_speech_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    context.bot.send_message(chat_id, f"<b>GPT4 + ElevenLabs</b>\nOutput messages are now only generated speech.", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': "speech"})

def output_image_command(update, context):
    chat_id = update.message.chat_id
    user_data_interact = db.collection('users').document(str(chat_id))
    context.bot.send_message(chat_id, f"<b>DALL·E 3</b>\nOutput messages are now only generated images.", parse_mode=telegram.ParseMode.HTML)
    user_data_interact.update({'output_message': "image"})

def chatgpt_completion(chat_id, text_message):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')

    if character_balance > 0:

        completion = client.chat.completions.create(      
            messages=[
                {'role': 'system', 'content': "Short sentence like in the real people conversation!!!"},
                {'role': 'user', 'content': text_message}
            ],
            model="gpt-4",
            temperature=0.3,
            # max_characters=500
        )    

        chatgpt_message = completion.choices[0].message.content
        character_count = len(chatgpt_message)

        character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')

        user_data_interact.update({
            'character_balance': character_balance - character_count
        })

    elif character_balance < 0:
        user_data_interact.update({
            'character_balance': 0
        })

    return chatgpt_message

def whisper_transcribe(chat_id, url, format):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')

    if character_balance > 0:

        response = requests.get(url)
        transcript = client.audio.transcriptions.create(
        model="whisper-1", 
        file=("name", response.content, format),
        response_format="text"     
        )

    elif character_balance < 0:
        user_data_interact.update({
            'character_balance': 0
        })

    return transcript

def elevenlab_voice(current_voice, chatgpt_message):          
    url = "https://api.elevenlabs.io/v1/text-to-speech/{}".format(current_voice)
    headers = {"Content-Type": "application/json", "xi-api-key": ELVENLABS_TOKEN}
    payload = {"text": chatgpt_message, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 1, "similarity_boost": 1}}
    response = requests.post(url, json=payload, headers=headers)
    return response.content

def dalle_image(chat_id, text_message):
    user_data_interact = db.collection('users').document(str(chat_id))
    character_balance = user_data_interact.get(['character_balance']).to_dict().get('character_balance')

    if character_balance > 0:
        response_dalle = client.images.generate(model="dall-e-3", prompt=text_message, size="1024x1024", quality="standard", n=1,)
        image_url = response_dalle.data[0].url 
        user_data_interact.update({'character_balance': character_balance - 250})

    elif character_balance < 0:
        user_data_interact.update({'character_balance': 0})

    return image_url          
    
def unknown_command_handler(update, context):
    chat_id = update.message.chat_id
    text_message = update.message.text
    text_message_split = str(text_message).split()
    command_list = ['/start', '/help', '/myprofile', '/payment', '/output', '/changevoice', '/clonevoice']
    if text_message_split[0].startswith("/") and text_message_split[0] not in command_list:
        context.bot.send_message(chat_id, "Please provide the correct command.")

#########################           HANDLES           ##########################
def handle_message(update, context):
    chat_id = update.message.chat_id
    text_message = update.message.text
    voice_message = update.message.voice  
    document_message = update.message.document
    audio_message = update.message.audio
    photo_message = update.message.photo    
    user_data_interact = db.collection('users').document(str(chat_id))
    output_message = user_data_interact.get(['output_message']).to_dict().get('output_message')
    current_voice = user_data_interact.get(['current_voice']).to_dict().get('current_voice')
        
    if output_message == 'text':
        try:
            if voice_message is not None:
                voice_format = update.message.voice.mime_type
                file_id = update.message.voice.file_id
                url = context.bot.get_file(file_id).file_path    
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)            
                transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
                chatgpt_message = chatgpt_completion(chat_id=chat_id, text_message=transcript)   
                context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
            elif text_message is not None:
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
                chatgpt_message = chatgpt_completion(chat_id=chat_id, text_message=text_message) 
                context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
            elif document_message is not None or audio_message is not None or photo_message is not None:
                context.bot.send_message(chat_id=chat_id, text="Can't process this data at the moment.")     
            else:
                context.bot.send_message(chat_id=chat_id, text="This data is not acceptable.")
        except:
            context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")

    elif output_message == 'speech':
        try:
            if voice_message is not None:
                voice_format = update.message.voice.mime_type
                file_id = update.message.voice.file_id
                url = context.bot.get_file(file_id).file_path    
                transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
                chatgpt_message = chatgpt_completion(chat_id=chat_id, text_message=transcript)
                if current_voice != "":   
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
                    elevenlab_output = elevenlab_voice(current_voice=current_voice, chatgpt_message=chatgpt_message)
                    context.bot.send_voice(chat_id=chat_id, voice=elevenlab_output)
                else:
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
                    context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
            elif text_message is not None:
                chatgpt_message = chatgpt_completion(chat_id=chat_id, text_message=text_message) 
                if current_voice != "":  
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.RECORD_VOICE)
                    elevenlab_output = elevenlab_voice(current_voice=current_voice, chatgpt_message=chatgpt_message)
                    context.bot.send_voice(chat_id=chat_id, voice=elevenlab_output)   
                else:
                    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.TYPING)
                    context.bot.send_message(chat_id=chat_id, text=chatgpt_message)
            elif document_message is not None or audio_message is not None or photo_message is not None:
                context.bot.send_message(chat_id=chat_id, text="Can't process this data at the moment.")     
            else:
                context.bot.send_message(chat_id=chat_id, text="This data is not acceptable.")   
        except:
            context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")

    elif output_message == 'image':
        try:
            if voice_message is not None:
                update.message.reply_text("Generating image. Please wait a few seconds...")
                voice_format = update.message.voice.mime_type
                file_id = update.message.voice.file_id
                url = context.bot.get_file(file_id).file_path    
                transcript = whisper_transcribe(chat_id=chat_id, url=url, format=voice_format)
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO)
                dalle_url = dalle_image(chat_id=chat_id, text_message=transcript)
                response = requests.get(dalle_url)
                context.bot.send_photo(chat_id=chat_id, photo=response.content)
            elif text_message is not None:
                update.message.reply_text("Generating image. Please wait a few seconds...")
                context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO)
                dalle_url = dalle_image(chat_id=chat_id, text_message=text_message)
                response = requests.get(dalle_url)
                context.bot.send_photo(chat_id=chat_id, photo=response.content)  
            elif document_message is not None or audio_message is not None or photo_message is not None:
                context.bot.send_message(chat_id=chat_id, text="Can't process this data at the moment.")     
            else:
                context.bot.send_message(chat_id=chat_id, text="This data is not acceptable.")
        except:
            context.bot.send_message(chat_id=chat_id, text="You reached the limit. If you still have characters, there might be technical difficulties.")                
    else:
        context.bot.send_voice(chat_id=chat_id, text="Technical difficulties")

#########################           COMBINING_ALL           ##########################
clone_handler = ConversationHandler(
    entry_points=[CommandHandler('clonevoice', clone_voice_command)],
    states={
        CLONE_VOICE_ACTION: [
            MessageHandler(Filters.text & ~Filters.command, clone_button_click),
            MessageHandler(Filters.voice | Filters.audio | Filters.document | Filters.text, receive_audio)
        ]
    },
    fallbacks=[]
)

dp.add_handler(clone_handler)
dp.add_handler(CommandHandler('start', start_command))
dp.add_handler(CommandHandler('help', help_command))
dp.add_handler(CommandHandler('myprofile', my_profile_command))
dp.add_handler(CommandHandler('payment', payment_command))
dp.add_handler(CommandHandler('outputtext', output_text_command))
dp.add_handler(CommandHandler('outputspeech', output_speech_command))
dp.add_handler(CommandHandler('outputimage', output_image_command))
dp.add_handler(CommandHandler('voicelibrary', voice_library_command))
dp.add_handler(CommandHandler('changevoice', change_voice_command))
dp.add_handler(CommandHandler('clonevoice', clone_voice_command))
dp.add_handler(CommandHandler('deleteclonevoice', delete_clone_voice_command))
dp.add_handler(CommandHandler("invoice", send_invoice))
dp.add_handler(PreCheckoutQueryHandler(pre_checkout_query))
dp.add_handler(MessageHandler(Filters.successful_payment, successful_payment))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command | Filters.voice | Filters.document | Filters.audio | Filters.photo, handle_message))
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
