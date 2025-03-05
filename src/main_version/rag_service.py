import os
from dotenv import load_dotenv
import string
import asyncio
from fastapi import FastAPI, WebSocket
import websockets
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.chat_models import GigaChat
from langchain_gigachat import GigaChat
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import create_retrieval_chain
from langchain.retrievers import EnsembleRetriever

load_dotenv()
# Инициализация FastAPI
app = FastAPI()

api_key = os.getenv("GIGACHAT_API_KEY")

folder_path_1 = os.path.join(os.path.dirname(__file__), "txt_docs/docs_pack_1")
folder_path_2 = os.path.join(os.path.dirname(__file__), "txt_docs/docs_pack_2")
folder_path_3 = os.path.join(os.path.dirname(__file__), "txt_docs/docs_pack_3")

folder_path_full = os.path.join(os.path.dirname(__file__), "txt_docs/docs_pack_full")

def create_docs_from_txt(folder_path):
    # Получаем список всех файлов .txt в указанной директории
    file_paths = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith(".txt")]

    # Список для хранения загруженных документов
    docs = []

    # Загружаем текст из файлов
    for file_path in file_paths:
        loader = TextLoader(file_path)
        docs.extend(loader.load())

    # Разделяем текст на чанки
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,  # Размер чанка
        chunk_overlap=100  # Перекрытие между чанками
    )
    split_docs = text_splitter.split_documents(docs)
    return split_docs

# Документы по Специалисту аналитику
split_docs_1 = create_docs_from_txt(folder_path_1)
# Документы по Лиду аналитику
split_docs_2 = create_docs_from_txt(folder_path_2)
# Документы по PO/PM
split_docs_3 = create_docs_from_txt(folder_path_3)
# Полный пакет
split_docs_full = create_docs_from_txt(folder_path_full)

# Инициализация модели для эмбеддингов
model_name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
model_kwargs = {'device': 'cpu'}
encode_kwargs = {'normalize_embeddings': False}
embedding = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs=model_kwargs,
    encode_kwargs=encode_kwargs
)

# Создание векторного хранилища 1
vector_store_1 = FAISS.from_documents(split_docs_1, embedding=embedding)
embedding_retriever_1 = vector_store_1.as_retriever(search_kwargs={"k": 5})

# Создание векторного хранилища 2
vector_store_2 = FAISS.from_documents(split_docs_2, embedding=embedding)
embedding_retriever_2 = vector_store_2.as_retriever(search_kwargs={"k": 5})

# Создание векторного хранилища 3
vector_store_3 = FAISS.from_documents(split_docs_3, embedding=embedding)
embedding_retriever_3 = vector_store_3.as_retriever(search_kwargs={"k": 5})

# Создание векторного хранилища со всеми данными
vector_store_full = FAISS.from_documents(split_docs_full, embedding=embedding)
embedding_retriever_full = vector_store_full.as_retriever(search_kwargs={"k": 5})


# Инициализация модели GigaChat

def create_retrieval_chain_from_folder(role, specialization, prompt_template, embedding_retriever):

    # Заполнение шаблона промпта
    template = string.Template(prompt_template)
    filled_prompt = template.substitute(role=role, specialization=specialization)

    # Создание промпта
    prompt = ChatPromptTemplate.from_template(filled_prompt)

    llm = GigaChat(
    credentials=api_key,
    model='GigaChat',
    verify_ssl_certs=False,
    profanity_check=False
)

    # Создание цепочки для работы с документами
    document_chain = create_stuff_documents_chain(
        llm=llm,
        prompt=prompt
    )

    # Создание retrieval_chain
    retrieval_chain = create_retrieval_chain(embedding_retriever, document_chain)

    return retrieval_chain

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Обрабатывает WebSocket соединение и передает стриминг ответа GigaChat."""
    await websocket.accept()
    question = await websocket.receive_text()
    role = await websocket.receive_text()
    specialization = await websocket.receive_text()
    question_id = await websocket.receive_text()
    question_id = int(question_id)
    print(question)
    print(role)
    print(specialization)
    prompt_template = ""
    embedding_retriever = embedding_retriever_full
    if (question_id == 1):
        embedding_retriever = embedding_retriever_1
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт по взаимодействию между аналитиками и менеджерами продуктов (PO) и проектными менеджерами (PM). Твоя задача – дать четкий и структурированный ответ на вопрос: "Что я могу ожидать от своего PO/PM?", основываясь на предоставленной базе знаний.
        Определение роли:
        Узнай роль пользователя (бизнес-аналитик, системный аналитик, продуктовый аналитик), чтобы адаптировать ответ.

        Структура ответа:
        Обязанности PO/PM: Опиши ключевые функции Product Owner (PO) и Project Manager (PM), их зоны ответственности и влияние на работу аналитика.
        Взаимодействие с аналитиком: Разъясни, какую поддержку можно ожидать от PO/PM в работе аналитика: постановка задач, доступ к информации, координация с командой.
        Ожидания в зависимости от уровня аналитика:

        Для Junior: PO/PM помогает с приоритезацией, обучением, уточнением требований.
        Для Middle: PO/PM ожидает проактивности в анализе, а сам обеспечивает доступ к бизнес-стейкхолдерам.
        Для Senior: PO/PM полагается на аналитика в стратегическом планировании и формировании продуктовой/проектной стратегии.
        Формат вывода:
        Используй четкую структуру с разделами: Обязанности PO/PM, Как взаимодействует с аналитиком, Ожидания в зависимости от уровня.
        Добавь примеры реальных ситуаций, где взаимодействие с PO/PM играет ключевую роль.
        Твой ответ не должен превысить 4096 символов.
        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 2):
        embedding_retriever = embedding_retriever_1

        prompt_template = '''
        На основе контекста, предоставленного в векторной базе данных, ответь на следующий вопрос:

        'Что я могу ожидать от своего лида компетенции?'

        При формировании ответа учти следующие параметры:

        Роль: $role
        Специализация: $specialization
        Типичные задачи и взаимодействия внутри команды.
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике
        должен исполнять в соответствии с указанными параметрами.
        Если в контексте недостаточно информации для точного ответа, пожалуйста,
        дай знать об этом и предложи уточнить вопрос или предоставить дополнительный контекст.
        Твой ответ не должен превысить 4096 символов.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 3):
        embedding_retriever = embedding_retriever_1

        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Ты – эксперт по составлению требований и описанию ролей для IT-специалистов.
        Сформулируй структурированный ответ на запрос, связанный с анализом матрицы компетенций для разных уровней специалистов используя данные из контекста.
        Ответ должен быть представлен в виде списка уровней Junior, Junior+/Middle-, Middle+ с разделением на soft skills (софты) и hard skills (харды) для каждого уровня.
        Если вам не хватает информации для ответа, сообщите об этом пользователю, а также предложите уточнить вопрос или предоставить дополнительный контекст.

        Пример ожидаемого формата ответа:

        Уровень Junior
        Софты:
        ...
        ...
        Харды:
        ...
        ...
        Уровень Junior+/Middle-
        Софты:
        ...
        ...
        Харды:
        ...
        ...
        И так далее для других уровней.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 4):
        embedding_retriever = embedding_retriever_2

        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области компетенций аналитиков. Твоя задача – дать четкий и структурированный ответ на вопрос: "Что я, как лид компетенции, могу ожидать от специалиста-аналитика?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Обязанности специалиста-аналитика: Опиши ключевые функции аналитика, его основные задачи и зону ответственности в рамках компетенции.
        Взаимодействие с лидом компетенции: Разъясни, какую поддержку аналитик должен оказывать лиду компетенции, его вклад в развитие направления и обмен знаниями.
        Ключевые компетенции: Укажи, какими знаниями, навыками и инструментами должен владеть аналитик для эффективного выполнения своих обязанностей.
        Ожидания от аналитика: Определи, какие профессиональные качества, инициативность и уровень вовлеченности должны быть у аналитика.

        Формат вывода:
        Используй четкую структуру с разделами: Обязанности аналитика, Взаимодействие с лидом компетенции, Ключевые компетенции, Ожидания от аналитика.
        Добавь примеры реальных ситуаций, где компетенции аналитика играют ключевую роль.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 5):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области взаимодействия аналитиков с Product Owner PO и Project Manager PM. Твоя задача – дать четкий и структурированный ответ на вопрос: "Что я, как лид компетенции аналитик, могу ожидать от PO PM специалиста?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Обязанности PO и PM Опиши ключевые функции Product Owner и Project Manager их зоны ответственности и влияние на работу аналитика
        Взаимодействие с лидом компетенции Разъясни какую поддержку можно ожидать от PO и PM в работе аналитика включая доступ к информации координацию процессов и влияние на стратегические решения
        Ожидания от PO и PM Определи какие профессиональные качества инициативность и уровень вовлеченности должны быть у этих специалистов чтобы эффективно взаимодействовать с аналитиками

        Формат вывода:
        Используй четкую структуру с разделами Обязанности PO и PM Как взаимодействуют с лидом компетенции Ожидания от PO и PM
        Добавь примеры реальных ситуаций где взаимодействие PO и PM с аналитиками играет ключевую роль

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 6):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области подбора и оценки кандидатов в команду аналитики. Твоя задача – дать четкий и структурированный ответ на вопрос: "Что ожидается от лида компетенции аналитики при поиске кандидатов на работу?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Определение требований Опиши, какие критерии должны быть сформулированы перед началом поиска кандидатов, включая ключевые компетенции и уровень владения инструментами
        Оценка технических навыков Разъясни, какие технические компетенции необходимо проверять в ходе интервью, включая владение инструментами анализа данных, знание клиент серверных взаимодействий и умение работать с бизнес требованиями
        Оценка софт скиллов Определи, какие личные качества и навыки коммуникации важны при отборе кандидатов и как их проверять
        Процесс отбора Опиши, как должен быть организован процесс найма, включая взаимодействие с HR командой и проведение технических интервью
        Адаптация новых сотрудников Разъясни, какие шаги должен предпринять лид компетенции аналитики для успешной интеграции новых сотрудников в команду

        Формат вывода:
        Используй четкую структуру с разделами Определение требований Оценка технических навыков Оценка софт скиллов Процесс отбора Адаптация новых сотрудников
        Добавь примеры реальных ситуаций, где эффективный процесс подбора аналитиков сыграл ключевую роль

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 7):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области найма и оценки аналитиков. Твоя задача – дать четкий и структурированный ответ на вопрос: "Что ожидается от лида компетенции аналитики при проведении собеседований?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Подготовка к собеседованию: Опиши, какие шаги должен предпринять лид компетенции перед проведением интервью, включая определение требований к кандидату, формирование критериев оценки и подготовку вопросов.
        Проведение технического интервью: Разъясни, какие аспекты технической подготовки необходимо проверять у кандидатов, включая владение инструментами анализа данных, работу с требованиями и понимание бизнес-процессов.
        Оценка софт-скиллов: Укажи, какие личные качества, навыки коммуникации и адаптивность к команде важно проверять, а также как это лучше делать в формате собеседования.
        Процесс принятия решений: Определи, как лид компетенции должен анализировать результаты интервью, взаимодействовать с HR-командой и другими руководителями, а также принимать финальное решение по кандидатам.
        Обратная связь и адаптация: Разъясни, как правильно давать кандидатам объективную обратную связь, участвовать в их адаптации и обеспечивать их интеграцию в команду после успешного найма.

        Формат вывода:
        Используй четкую структуру с разделами. Подготовка к собеседованию, Проведение технического интервью, Оценка софт-скиллов, Процесс принятия решений, Обратная связь и адаптация.
        Добавь примеры реальных ситуаций, где грамотный процесс собеседования позволил найти сильного кандидата и улучшить команду.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 8):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области наставничества и развития аналитиков начального уровня. Твоя задача – дать четкий и структурированный ответ на вопрос: "Что ожидается от лида компетенции аналитики при работе со стажерами и джунами?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Наставничество и поддержка Опиши, какие аспекты профессионального развития стажеров и джунов должен курировать лид компетенции, включая обучение базовым аналитическим навыкам и адаптацию к рабочим процессам
        Обучение и развитие Разъясни, какие методы и подходы следует использовать для передачи знаний, оценки прогресса и выявления пробелов в компетенциях молодых специалистов
        Погружение в рабочие процессы Определи, как лид компетенции должен вовлекать стажеров и джунов в проектную работу, делегировать задачи и контролировать их выполнение
        Обратная связь и развитие софт скиллов Разъясни, как правильно организовывать процесс регулярных встреч, предоставлять конструктивную обратную связь и развивать у молодых специалистов навыки коммуникации, работы в команде и принятия ответственности

        Формат вывода:
        Используй четкую структуру с разделами Наставничество и поддержка Обучение и развитие Погружение в рабочие процессы Обратная связь и развитие софт скиллов
        Добавь примеры реальных ситуаций, где эффективное наставничество помогло ускорить рост стажеров и джунов и повысить их вклад в работу команды

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 9):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Основываясь на контексте, доступном в векторной базе данных, дай ответ на вопрос: \
        'Что ожидается от лида компетенции при проведение 1-2-1?' \
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике должен исполнять.
        Если недостаточно информации для точного ответа,
        сообщи об этом и предложи уточнить вопрос или предоставить дополнительный контекст.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 10):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Основываясь на контексте, доступном в векторной базе данных, дай ответ на вопрос: \
        'Что ожидается от лида компетенции при проведение встречи компетенции?' \
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике должен исполнять,\
        учитывая роль $role и специализацию — $specialization человека, который задает вопрос.
        Если недостаточно информации для точного ответа,
        сообщи об этом и предложи уточнить вопрос или предоставить дополнительный контекст.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 11):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Основываясь на контексте, доступном в векторной базе данных, дай ответ на вопрос: \
        'Что ожидается от лида компетенции при построение структуры компетенции?' \
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике должен исполнять,\
        учитывая роль $role и специализацию — $specialization человека, который задает вопрос.
        Если недостаточно информации для точного ответа,
        сообщи об этом и предложи уточнить вопрос или предоставить дополнительный контекст.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 12):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Основываясь на контексте, доступном в векторной базе данных, дай ответ на вопрос: \
        'Что ожидается от лида компетенции при создании ИПР?' \
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике должен исполнять,\
        учитывая роль $role и специализацию — $specialization человека, который задает вопрос.
        Если недостаточно информации для точного ответа,
        сообщи об этом и предложи уточнить вопрос или предоставить дополнительный контекст.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''

    elif (question_id == 13):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.

        Промпт:
        Ты – эксперт в области адаптации новых сотрудников. Твоя задача – дать четкий и структурированный ответ на вопрос: "Как лид компетенции аналитики должен проводить онбординг нового сотрудника?", основываясь на предоставленной базе знаний.

        Структура ответа:
        Подготовка к онбордингу. Опиши, какие шаги необходимо предпринять до прихода нового сотрудника, включая подготовку доступа, документов и программы адаптации.
        Знакомство с рабочими процессами. Разъясни, какие ключевые процессы, инструменты и методологии работы должен освоить новый аналитик, а также как организовать вводные встречи.
        Назначение задач и вовлечение в работу Определи, какие начальные задачи следует дать новичку, как правильно вводить его в проектную деятельность и обучать работе с данными и требованиями.
        Обратная связь и контроль адаптации. Разъясни, как организовать регулярные встречи для обсуждения прогресса, предоставления обратной связи и корректировки адаптационного плана.

        Формат вывода:
        Используй четкую структуру с разделами. Подготовка к онбордингу. Знакомство с рабочими процессами Назначение задач и вовлечение в работу. Обратная связь и контроль адаптации.
        Добавь примеры реальных ситуаций, где эффективный онбординг помог ускорить адаптацию аналитика и повысить его продуктивность.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''

    elif (question_id == 14):
        embedding_retriever = embedding_retriever_2
        prompt_template = '''
        Основываясь на контексте, доступном в векторной базе данных, дай ответ на вопрос: \
        'Как лид компетенции аналитики должен оптимизировать процессы разработки?' \
        Опиши основные ожидания и роли, которые лидер компетенции по аналитике должен исполнять, \
        учитывая его ответственность за анализ текущих рабочих процессов, взаимодействие с командой и внедрение улучшений. \
        Разъясни, какие методологии, инструменты и подходы к автоматизации могут повысить эффективность процессов разработки, \
        как аналитик должен участвовать в улучшении коммуникации между командами и как оценивать результаты внедренных изменений.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 15):
        embedding_retriever = embedding_retriever_3
        prompt_template = '''
        Ты исполняешь роль product owner.
        Твоя задача — объяснить другому product owner, что он может ожидать от системного аналитика. Ориентируйся на следующие ключевые аспекты:

        Как системный аналитик поможет в определении и документировании требований.
        Какие преимущества даст анализ текущих процессов и систем.
        Как моделирование решений и их визуализация могут упростить взаимодействие.
        Как системный аналитик поддержит реализацию новых функций.
        Какой интерес представляет анализ данных и метрик успеха.
        Почему важна эффективная коммуникация и сотрудничество.
        Постарайся сделать ответ информативным, дружелюбным и понятным.
        Предоставь четкую и логически структурированную информацию, основываясь на предоставленных пунктах и контексте из векторной базы данных.
        Если тебе не хватает информации для ответа, сообщи об этом пользователю.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    elif (question_id == 16):
        embedding_retriever = embedding_retriever_3
        prompt_template = '''
        Вы исполняете роль product owner.
        Ваши функции включают:

        Решение вопросов, связанных с системной аналитикой, используя данные из контекста.
        Консультирование и предложение рекомендаций, необходимых для выполнения задач в рамках product owner.
        Предоставление информации и помощь в решении проблем в контексте взаимодействия product owner и лида компетенции.
        На основе предоставленного контекста, \
        ответьте на вопрос пользователя, уделяя внимание его роли и специализации. \
        Если тебе не хватает информации для ответа, сообщи об этом пользователю.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    
    elif (question_id == 17):
        embedding_retriever = embedding_retriever_3
        prompt_template = '''
        Представь себя коучем для Product Owner в команде разработки программного обеспечения.
        Объясни ему основные задачи и роли, которые он должен выполнять.
        Уточни, что от него ожидается на каждом этапе процесса разработки.
        Подчеркни важность каждой задачи и предложи примеры инструментов или методов, которые могут помочь в их выполнении.
        На основе предоставленного контекста, \
        ответьте на вопрос пользователя, уделяя внимание его роли и специализации. \
        Если тебе не хватает информации для ответа, сообщи об этом пользователю.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''
    
    
    elif(question_id == 777):
        embedding_retriever = embedding_retriever_full

        prompt_template = '''
        Вы исполняете роль $role, а ваша специализация — $specialization.
        Ваши функции включают:

        Решение вопросов, связанных с $specialization, используя данные из контекста.
        Консультирование и предложение рекомендаций, необходимых для выполнения задач в рамках $role.
        Предоставление информации и помощь в решении проблем в контексте $specialization и $role.
        На основе предоставленного контекста, \
        ответьте на вопрос пользователя, уделяя внимание его роли и специализации. \
        Если вам не хватает информации для ответа, сообщите об этом пользователю, \
        а также предложите уточнить вопрос или предоставить дополнительный контекст.
        Твой ответ не должен превысить 4096 символов.

        Контекст: {context}
        Вопрос: {input}
        Ответ:
        '''        

    print(f"📩 Получен запрос: {question}")

    retrieval_chain = create_retrieval_chain_from_folder(role, specialization, prompt_template, embedding_retriever)

    # Задаем массив лишних символов
    unwanted_chars = ["*", "**"]
    # Запускаем стриминг ответа
    async for chunk in retrieval_chain.astream({'input': question}):
        if chunk:
                # Извлекаем ответ
            answer = chunk.get("answer", "").strip()

                # Заменяем ненужные символы
            for char in unwanted_chars:
                answer = answer.replace(char, " ")
                
            answer = " ".join(answer.split())  # Удаляем лишние пробелы
                
            await websocket.send_text(answer)  # Отправляем очищенный текстовый ответ
    
    await websocket.close()

if __name__ == "__main__":
    import uvicorn
    print("Запускаем сервер на ws://127.0.0.1:8000/ws")
    uvicorn.run(app, host="0.0.0.0", port=8000)
