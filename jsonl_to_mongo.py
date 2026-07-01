import json
import certifi  # ОБЯЗАТЕЛЬНО
from pymongo import MongoClient

# Вставьте вашу строку (БЕЗ скобок < >)
MONGO_URI = 'mongodb+srv://alshfu86:as785ghqw590!Q@cluster0.hm5obgl.mongodb.net/?appName=Cluster0'
DB_NAME = 'merinfo_db'
COLLECTION_NAME = 'companies'
JSONL_FILE = 'merinfo_bankgiro_full.jsonl'
BATCH_SIZE = 1000


def import_jsonl_to_mongo():
    try:
        # !!! ВОТ ЭТА ЧАСТЬ КРИТИЧЕСКИ ВАЖНА ДЛЯ MAC !!!
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())

        client.admin.command('ping')
        print("Успешное подключение к MongoDB Atlas!")

        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return

    # ... (дальше ваш код чтения файла без изменений) ...
    buffer = []
    count = 0
    try:
        with open(JSONL_FILE, 'r', encoding='utf-8') as file:
            print("Начинаю импорт...")
            for line in file:
                line = line.strip()
                if not line: continue
                try:
                    doc = json.loads(line)
                    buffer.append(doc)
                    if len(buffer) >= BATCH_SIZE:
                        collection.insert_many(buffer)
                        count += len(buffer)
                        print(f"Вставлено {count} документов...")
                        buffer = []
                except json.JSONDecodeError:
                    pass
            if buffer:
                collection.insert_many(buffer)
                count += len(buffer)
            print(f"Готово! Всего: {count}")
    except Exception as e:
        print(f"Ошибка: {e}")
if __name__ == "__main__":
    import_jsonl_to_mongo()