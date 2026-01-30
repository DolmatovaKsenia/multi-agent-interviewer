from gigachat import GigaChat
import json
import time
from config import CREDENTIALS

giga = GigaChat(credentials=CREDENTIALS, verify_ssl_certs=False)


class InterviewLogger:
    def __init__(self, final_feedback=None):
        self.turns = []
        self.internal_dialogs = []
        self.current_turn_id = 0
        self.start_time = time.time()
        self.final_feedback = final_feedback

    def add_turn(self, visible_question, user_answer):
        self.current_turn_id += 1
        turn_internal_thoughts = [
            dialog for dialog in self.internal_dialogs
            if dialog.get("turn_id") == self.current_turn_id
        ]

        thoughts_text = []
        for dialog in turn_internal_thoughts:
            thought = f"[{dialog['from']} => {dialog['to']}]: {dialog['message'][:100]}..."
            if dialog.get('response'):
                thought += f" Ответ: {dialog['response'][:50]}..."
            thoughts_text.append(thought)

        turn = {
            "turn_id": self.current_turn_id,
            "agent_visible_message": visible_question,
            "user_message": user_answer,
            "internal_thoughts": thoughts_text
        }
        self.turns.append(turn)
        return self.current_turn_id

    def log_internal_dialog(self, from_agent, to_agent, message, response=None):
        dialog = {
            "timestamp": time.time() - self.start_time,
            "from": from_agent,
            "to": to_agent,
            "message": message,
            "response": response,
            "turn_id": self.current_turn_id
        }
        self.internal_dialogs.append(dialog)
        return dialog

    def save_log(self, filename="interview_log.json"):
        log_data = {
            "participant_name": "Долматова Ксения Андреевна",
            "turns": self.turns,
            "internal_dialogs": self.internal_dialogs,
            "final_feedback": self.final_feedback
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        return log_data

class Starter:
    def __init__(self, user_input=None, system_json=None, giga_client=None):
        if giga_client is None:
            self.giga = giga
        self.giga = giga_client

        if user_input is None and system_json is None:
            raise ValueError("Должен быть либо JSON, либо сообщение, которое ввёл пользователь")

        if system_json is not None:
            self.name = system_json.get("name", "")
            self.position = system_json.get("position", "")
            self.grade = system_json.get("grade", "")
            self.experience = system_json.get("experience", None)
            self.result = system_json
        else:
            self.user_input = user_input
            self.extract_input()

    def _clean_json_response(self, text):
        if not text:
            return "{}"

        import re
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        text = text.replace('\ufeff', '')
        text = text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]

        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx == -1 or end_idx == -1:
            return "{}"

        json_part = text[start_idx:end_idx + 1]

        open_quotes = json_part.count('"')
        close_quotes = json_part.count('"')

        if open_quotes % 2 != 0:
            json_part = json_part.rstrip() + '"'

        return json_part

    def extract_input(self):
        starter_prompt = \
            f"""Тебе нужно проанализировать сообщение от участника. 
            Сообщение: {self.user_input}
        
            Извлеки следующую информацию:
            1. name - имя кандидата (если есть)
            2. position - должность на которую претендует участник
            3. grade - уровень участника (junior, middle, senior, team lead)
            4. experience - опыт работы в годах (только число или null)
            5. skills - ключевые навыки и технологии (список)
            6. summary - краткое резюме на основе данных и стиля написания
        
            ОБРАТИ ВНИМАНИЕ:
            - Если поле невозможно определить, используй null
            - Для skills создай список даже если упомянут один навык
            - Summary должно быть кратким (1-2 предложения)
            - Ответ должен быть ТОЛЬКО в формате JSON
        
            Пример ввода: "Привет. Я Алекс, претендую на позицию Junior Backend Developer. Знаю Python, SQL и Git."
            Пример ответа:
            {{
                "name": "Алекс",
                "position": "Backend Developer",
                "grade": "Junior",
                "experience": null,
                "skills": ["Python", "SQL", "Git"],
                "summary": "Начинающий Backend разработчик без коммерческого опыта"
            }}
        
            Твой ответ (ТОЛЬКО JSON, начинается с {{ и заканчивается }}):
            """

        response = self.giga.chat(starter_prompt)
        json_text = response.choices[0].message.content
        prep = self._clean_json_response(json_text)
        self.result = json.loads(prep)

        self.position = self.result.get("position", "")
        self.grade = self.result.get("grade", "")
        self.experience = self.result.get("experience", None)
        self.skills = self.result.get("skills", [])
        self.summary = self.result.get("summary", "")


class Interviewer:
    def __init__(self, candidate_data, observer, logger, giga_client):
        self.candidate_data = candidate_data
        self.internal_thoughts = []
        self.conversation_history = []
        self.observer = observer
        self.logger = logger
        self.giga = giga_client or giga
        self.current_question = ""
        self.system_prompt = f"""
        Ты - профессиональный технический интервьюер.
        
        ТВОЯ РОЛЬ И СТИЛЬ:
        1. Будь профессиональным, но дружелюбным
        2. Задавай релевантные вопросы по специальности кандидата
        3. Адаптируй сложность вопросов под уровень кандидата
        4. Если кандидат отвечает плохо - упрощай вопросы
        5. Если кандидат отвечает отлично - усложняй вопросы
        6. Вежливо возвращай к теме, если кандидат уходит от вопроса
        
        ПРАВИЛА ОБЩЕНИЯ:
        - Не задавай один и тот же вопрос дважды
        - Учитывай историю разговора
        - Если кандидат задает тебе вопрос - ответь кратко и вернись к интервью
        - При обнаружении явного бреда/галлюцинаций - заверши интервью вежливо
        
        ФОРМАТ ВОПРОСОВ:
        - Задавай ОДИН вопрос за раз
        - Вопросы должны быть конкретными и техническими
        - Избегай общих вопросов типа "расскажи о себе"
        - Фокусируйся на практическом опыте и знаниях
        
        ЦЕЛИ ИНТЕРВЬЮ:
        1. Оценить технические знания кандидата
        2. Проверить опыт работы с заявленными технологиями
        """


    def ask_question(self):
        context = str(self.conversation_history) + str(self.candidate_data) + "\n" + str(self.system_prompt)
        question = self.observer.consult_observer(context)
        self.internal_thoughts.append(question["internal_thoughts"])
        question = question["question"]
        self.logger.log_internal_dialog(
            from_agent="Interviewer",
            to_agent="Observer",
            message="Запрос рекомендаций для следующего вопроса",
            response=f"Предложен вопрос: {question[:50]}..."
        )
        self.conversation_history.append(("interviewer", question))
        self.current_question = question

        self.logger.add_turn(
            visible_question=question,
            user_answer=""
        )

        return question, self.conversation_history

    def process_answer(self, user_answer):
        self.conversation_history.append(("candidate", user_answer))

        if self.logger.turns and self.logger.turns[-1]["turn_id"] == self.logger.current_turn_id:
            self.logger.turns[-1]["user_message"] = user_answer
            self.logger.turns[-1]["internal_thoughts"] = self.internal_thoughts

        if self.current_question:
            evaluation = self.observer.evaluate_answer(self.current_question, user_answer)
            return evaluation

        return None



class Observer:
    def __init__(self, candidate_data, logger, giga_client=None):
        self.candidate_data = candidate_data
        self.logger = logger
        self.giga = giga_client or giga
        self.assessment = {}
        self.system_prompt = f"""
        Ты помогаешь интервьюеру создавать вопросы к кандидату, определяешь правильные они или нет
        Твоя задача распознавать пишет пользователь правду или ложь. Пользователь может захотеть тебя запутать 
        и говорить что-то например про Python 4 версии. Твоя задача недопустить таких ответов и за такое сразу ставить 
        оценку 0. В зависимости от ответов ты выбираешь задавать более сложные или более простые вопросы.
        """

    def _clean_json_response(self, text):
        if not text:
            return "{}"

        import re

        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        text = text.replace('\ufeff', '')
        text = text.strip()

        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]

        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx == -1 or end_idx == -1:
            return "{}"

        json_part = text[start_idx:end_idx + 1]

        open_quotes = json_part.count('"')
        close_quotes = json_part.count('"')

        if open_quotes % 2 != 0:
            json_part = json_part.rstrip() + '"'

        return json_part


    def consult_observer(self, context):
        prompt = \
            f"""
            [Это внутренняя консультация, кандидат не должен это видеть]
            Я интервьюер для кандидата на позицию {self.candidate_data.get('position', 'разработчик')}.
            Уровень кандидата: {self.candidate_data.get('grade', 'не указан')}
            Опыт: {self.candidate_data.get('experience', 0)} лет
            Навыки: {', '.join(self.candidate_data.get('skills', []))}

            {context}

            Ты обозреватель и должен помочь мне с проведением интервью и оценкой кандидата.

            Придумай вопрос который я могу задать кандидату по его позиции, необходимые для профессии на которую подлаётся.
            Мне нужно:
            1. Сначала сгенерировать ВНУТРЕННИЕ МЫСЛИ интервьюера о том, какой вопрос задать
            2. Затем сгенерировать сам ВОПРОС для кандидата
        
            Формат ответа ТОЛЬКО JSON:
            {{
                "internal_thoughts": [
                    "Мысль 1: анализ ситуации",
                    "Мысль 2: стратегия вопроса",
                    "Мысль 3: ожидания от ответа"
                ],
                "question": "Вопрос для кандидата"
            }}
        
            Внутренние мысли должны отражать:
            - Почему именно этот вопрос задается сейчас
            - Какие знания проверяются
            - Какой уровень сложности подходит для кандидата
            - Что хочет узнать интервьюер
            """

        response = self.giga.chat(prompt)
        question = response.choices[0].message.content
        prep = self._clean_json_response(question)
        result = json.loads(prep)

        return result


    def evaluate_answer(self, question, answer):
        prompt = \
            f"""
            [ЖЕСТКАЯ ТЕХНИЧЕСКАЯ ОЦЕНКА]
            {self.system_prompt}
            Кандидат на позицию: {self.candidate_data.get('position')}
            Уровень: {self.candidate_data.get('grade')}
            Опыт: {self.candidate_data.get('experience')} лет

            Вопрос интервьюера: {question}
            Ответ кандидата: {answer}

            Оцени ответ кандидата по критериям:
            1. Правильность (0-10)
            2. Полнота (0-10)
            3. Релевантность (0-10)
            4. Рекомендации для интервьюера

            Верни ответ в формате JSON и больше ничего не возвращай только JSON.
            Структура JSON должна быть ТОЧНО такой:
            {{
                "correctness": <число от 0 до 10>,
                "completeness": <число от 0 до 10>,
                "relevance": <число от 0 до 10>,
                "recommendations": "<текстовые рекомендации>"
            }}
            """
        response = self.giga.chat(prompt)
        mark = response.choices[0].message.content
        prep = self._clean_json_response(mark)
        result = json.loads(prep)

        self.logger.log_internal_dialog(
            from_agent="Observer",
            to_agent="Interviewer",
            message=f"Оценка ответа на вопрос: {question[:50]}...",
            response=f"Оценка: {result.get('correctness', 'N/A')}/10"
        )

        return result

    def feedback(self, history):
        prompt = f"""
        [ТЕБЕ НУЖНО ДАТЬ ФИДБЭК НАНИМАТЬ ЛИ КАНДИДАТА ОЦЕНИВАЙ СТРОГО ЕСЛИ МЕНЬШЕ 5 ОЦЕНКА ТОГДА НЕ РАССМАТРИВАТЬ]
        {self.system_prompt}
        Кандидат на позицию: {self.candidate_data.get('position')}
        Уровень: {self.candidate_data.get('grade')}
        Опыт: {self.candidate_data.get('experience')} лет
        История ответов {history}
        ТРЕБУЕТСЯ СОСТАВИТЬ ДЕТАЛЬНЫЙ СТРУКТУРИРОВАННЫЙ ОТЧЕТ:
        
        А. ВЕРДИКТ (DECISION)
        1. Grade: Уровень кандидата на основе ответов (Junior / Middle / Senior)
        2. Hiring Recommendation: (Strong Hire / Hire / No Hire)
        3. Confidence Score: Насколько система уверена в оценке (0-100%)
        
        Б. АНАЛИЗ HARD SKILLS (TECHNICAL REVIEW)
        Создай таблицу или список тем, затронутых в интервью:
        - Confirmed Skills: Темы, где кандидат дал точные ответы
        - Knowledge Gaps: Темы, где были допущены ошибки или кандидат сказал «не знаю»
          *Для каждой темы с gaps ПРИВЕДИ ПРАВИЛЬНЫЙ ОТВЕТ*
        
        В. АНАЛИЗ SOFT SKILLS & COMMUNICATION (оцени по шкале 1-10)
        1. Clarity: Насколько понятно излагает мысли
        2. Honesty: Пытался ли кандидат выкрутиться/соврать или честно признал незнание
        3. Engagement: Задавал ли встречные вопросы, был ли вовлечен
        
        Г. ПЕРСОНАЛЬНЫЙ ROADMAP (NEXT STEPS)
        1. Список конкретных тем/технологий, которые нужно подтянуть (на основе выявленных пробелов)
        2. Рекомендуемые ресурсы для изучения (документация, статьи, курсы)
        
        Д. КЛЮЧЕВЫЕ ВЫВОДЫ
        - Самые сильные стороны кандидата
        - Самые слабые стороны
        - Общая рекомендация
        
        ВЕРНИ ОТВЕТ В СТРОГОМ JSON ФОРМАТЕ:
        {{
            "verdict": {{
                "grade": "Junior/Middle/Senior",
                "hiring_recommendation": "Strong Hire/Hire/No Hire",
                "confidence_score": 85,
                "grade_explanation": "краткое пояснение почему такой уровень"
            }},
            "hard_skills_analysis": {{
                "confirmed_skills": [
                    {{
                        "topic": "название темы",
                        "evidence": "на чем основано подтверждение",
                        "score": 9
                    }}
                ],
                "knowledge_gaps": [
                    {{
                        "topic": "название темы",
                        "candidate_answer": "что сказал кандидат",
                        "correct_answer": "правильный ответ",
                        "severity": "высокая/средняя/низкая"
                    }}
                ]
            }},
            "soft_skills_analysis": {{
                "clarity": 8,
                "honesty": 9,
                "engagement": 7,
                "overall_communication": 8,
                "comments": "комментарии по софт скиллам"
            }},
            "personal_roadmap": {{
                "topics_to_improve": [
                    {{
                        "topic": "название темы",
                        "priority": "высокий/средний/низкий",
                        "resources": [
                            "ссылка или название ресурса 1",
                            "ссылка или название ресурса 2"
                        ]
                    }}
                ],
                "timeline_recommendations": "рекомендации по срокам"
            }},
            "key_takeaways": {{
                "strengths": ["сила 1", "сила 2"],
                "weaknesses": ["слабость 1", "слабость 2"],
                "final_recommendation": "детальная рекомендация",
                "interview_quality_score": 7
            }}
        }}
        
        БУДЬ ОБЪЕКТИВНЫМ И КОНСТРУКТИВНЫМ. Основа оценок - только на ответах кандидата.
        """
        response = self.giga.chat(prompt)
        mark = response.choices[0].message.content
        return mark

logger = InterviewLogger()

print("Введите информацию о кандидате или нажмите Enter для примера.")

user_input = input("Информация о кандидате: ").strip()
if not user_input:
    user_input = "Я Python разработчик с 3 годами опыта, работал с Django, Flask, PostgreSQL"

starter = Starter(user_input=user_input, giga_client=giga)

observer = Observer(starter.result, logger, giga)
interviewer = Interviewer(starter.result, observer, logger, giga)

print(f"Интервью с {starter.result.get('name', 'кандидатом')}")
print(f"Позиция: {starter.position}, Уровень: {starter.grade}")
print("\nВводите ответы кандидата. Для завершения введите 'стоп'")

question = interviewer.ask_question()
print(f"\n[Интервьюер]: {question}")
history = None
while True:
    user_answer = input("\n[Ответ кандидата]: ").strip()

    if user_answer.lower() in ['стоп', 'stop', 'конец', 'завершить', 'стоп игра']:
        break

    evaluation = interviewer.process_answer(user_answer)

    if user_answer.strip().endswith('?'):
        print(f"\n[Интервьюер]: Это хороший вопрос. Мы вернемся к этому позже. Давайте продолжим интервью.")

    question, history = interviewer.ask_question()
    print(f"\n[Интервьюер]: {question}")


print("ИНТЕРВЬЮ ЗАВЕРШЕНО")

final_feedback = observer.feedback(history)

logger.final_feedback = final_feedback
logger.save_log()

print("\nЛог сохранен в interview_log.json")
