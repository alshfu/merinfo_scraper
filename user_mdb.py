import pymongo
import bcrypt
import certifi
import datetime
from pymongo import MongoClient

# --- НАСТРОЙКИ ---
# Ваш URI (пароль скрыт для безопасности, вставьте свой)
MONGO_URI = 'mongodb+srv://alshfu86:as785ghqw590!Q@cluster0.hm5obgl.mongodb.net/?appName=Cluster0'


def init_crm_database():
    try:
        # 1. Подключение
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        db = client['crm_db']

        col_users = db['users']
        col_leads = db['leads']

        print("--- Настройка коллекции Users ---")
        # Индекс: логин должен быть уникальным
        col_users.create_index("username", unique=True)

        # Создаем менеджера (если нет)
        manager_username = "user_5"
        if not col_users.find_one({"username": manager_username}):
            # Хешируем пароль
            hashed_pw = bcrypt.hashpw("password_5".encode('utf-8'), bcrypt.gensalt())

            user_id = col_users.insert_one({
                "username": manager_username,
                "password_hash": hashed_pw.decode('utf-8'),
                "full_name": "Alex Hunter",
                "role": "manager",
                "created_at": datetime.datetime.utcnow()
            }).inserted_id
            print(f"✅ Менеджер {manager_username} создан. ID: {user_id}")
        else:
            user_data = col_users.find_one({"username": manager_username})
            user_id = user_data['_id']
            print(f"ℹ️ Менеджер {manager_username} уже существует. ID: {user_id}")

        print("\n--- Настройка коллекции Leads (История работы) ---")
        # Индекс 1: Чтобы быстро искать по Org Number (не дублировать работу)
        col_leads.create_index("org_number", unique=True)

        # Индекс 2: Чтобы менеджер быстро видел "Мои компании"
        col_leads.create_index("assigned_to")

        # Индекс 3: Чтобы фильтровать по статусу (например, "Показать все Отказы")
        col_leads.create_index("status")

        # --- ПРИМЕР: Как выглядит документ, когда менеджер поработал ---
        # Допустим, Алекс взял компанию 556660-6470
        sample_org = "556660-6470"

        # Проверим, нет ли её уже
        if not col_leads.find_one({"org_number": sample_org}):
            lead_doc = {
                "org_number": sample_org,  # Ссылка на merinfo_db
                "assigned_to": user_id,  # Кто работает (Алекс)
                "status": "THINKING",  # Текущий статус (Думает)
                "created_at": datetime.datetime.utcnow(),  # Когда взял в работу

                # ИСТОРИЯ СТАТУСОВ И ЗАМЕТКИ
                # Это массив, куда мы дописываем каждое действие
                "history": [
                    {
                        "date": datetime.datetime.utcnow() - datetime.timedelta(days=1),
                        "action": "STATUS_CHANGE",
                        "details": "Взял в работу (Status: NEW)"
                    },
                    {
                        "date": datetime.datetime.utcnow() - datetime.timedelta(days=1),
                        "action": "CALL",
                        "details": "Не дозвонился, автоответчик.",
                        "note": "Попробую завтра."
                    },
                    {
                        "date": datetime.datetime.utcnow(),
                        "action": "CALL",
                        "details": "Дозвонился до директора (Анника).",
                        "note": "Ей 72 года, хочет продать, но сомневается в цене. Договорились созвониться через неделю.",
                        "new_status": "THINKING"
                    }
                ],

                # Дата следующего контакта (для напоминания)
                "next_follow_up": datetime.datetime.utcnow() + datetime.timedelta(days=7)
            }

            col_leads.insert_one(lead_doc)
            print(f"✅ Создан пример карточки работы для компании {sample_org}")
        else:
            print(f"ℹ️ Карточка для {sample_org} уже  есть.")

        print("\nУСПЕХ! База данных CRM готова к работе.")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    init_crm_database()