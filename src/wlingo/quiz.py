import random
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from .models import Question
from .vocabulary import VocabularyManager


# --- Strategy Pattern: Quiz Generators ---
class QuizGenerator(ABC):
    """Abstract Base Class for different quiz generation strategies."""

    @abstractmethod
    def generate(self, topic: str, count: int) -> List[Question]:
        pass


class ArithmeticQuizGenerator(QuizGenerator):
    """Generates arithmetic quizzes for elementary school kids."""

    def generate(self, topic: str, count: int) -> List[Question]:
        questions = []
        for _ in range(count):
            op = random.choice(["+", "-"])
            if op == "+":
                a = random.randint(1, 20)
                b = random.randint(1, 20)
                answer = a + b
                question_text = f"{a} + {b}"
            else:
                a = random.randint(5, 20)
                b = random.randint(1, a)
                answer = a - b
                question_text = f"{a} - {b}"

            options = self._generate_options(str(answer))
            questions.append(
                Question(word=question_text, translation=str(answer), options=options)
            )
        return questions

    def _generate_options(self, correct_answer: str) -> List[str]:
        """Helper to generate random distractors for arithmetic questions."""
        correct_answer_int = int(correct_answer)
        options = {correct_answer_int}
        while len(options) < 4:
            # Generate distractors close to the correct answer
            offset = random.randint(-5, 5)
            if offset == 0:
                continue
            distractor = correct_answer_int + offset
            if distractor >= 0:
                options.add(distractor)

        str_options = [str(opt) for opt in options]
        random.shuffle(str_options)
        return str_options


class RandomQuizGenerator(QuizGenerator):
    """Standard mode: Randomly selects N words from the topic."""

    def __init__(self, vocab_manager: VocabularyManager):
        self.vocab_manager = vocab_manager

    def generate(self, topic: str, count: int) -> List[Question]:
        word_list = self.vocab_manager.get_words(topic)
        if not word_list:
            return []

        selected_words = random.sample(word_list, min(count, len(word_list)))

        return [
            Question(
                word=item["word"],
                translation=item["translation"],
                options=self._generate_options(item["translation"], word_list),
            )
            for item in selected_words
        ]

    def _generate_options(
        self, correct_translation: str, all_words: List[Dict[str, str]]
    ) -> List[str]:
        """Helper to generate random distractors."""
        all_translations = {w["translation"] for w in all_words}
        all_translations.discard(correct_translation)

        num_options = 3
        if len(all_translations) < num_options:
            incorrect = list(all_translations)
            while len(incorrect) < num_options:
                incorrect.append(f"Option {len(incorrect)+1}")
        else:
            incorrect = random.sample(list(all_translations), num_options)

        options = [correct_translation] + incorrect
        random.shuffle(options)
        return options


class QuizFactory:
    """Factory to select the appropriate generator."""

    @staticmethod
    def create(
        mode: str, vocab_manager: Optional[VocabularyManager] = None
    ) -> QuizGenerator:
        if mode == "arithmetic":
            return ArithmeticQuizGenerator()
        elif mode == "standard":
            if not vocab_manager:
                raise ValueError("VocabularyManager is required for standard mode")
            return RandomQuizGenerator(vocab_manager)
        else:
            # Fallback for any other mode will be standard
            if not vocab_manager:
                raise ValueError("VocabularyManager is required for standard mode")
            return RandomQuizGenerator(vocab_manager)
