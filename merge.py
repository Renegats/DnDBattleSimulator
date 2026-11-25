from pathlib import Path


def collect_python_contents():
    # Получаем директорию, в которой лежит текущий скрипт
    current_dir = Path(__file__).parent
    current_script = Path(__file__).name

    # Динамически находим все .py файлы.
    # Исключаем сам скрипт, чтобы его код не попал в итоговый файл.
    py_files = sorted(f for f in current_dir.glob('*.py') if f.name != current_script)

    if not py_files:
        print("В папке не найдено других .py файлов.")
        return

    output_file = current_dir / 'all_python_contents.txt'

    # Открываем файл для записи (utf-8 для поддержки кириллицы и спецсимволов)
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for py_file in py_files:
            # Добавляем заголовок и разделитель для структурирования документа
            out_f.write(f"\n{'=' * 20} {py_file.name} {'=' * 20}\n\n")

            # Читаем и записываем содержимое
            # errors='replace' предотвратит краш скрипта, если вдруг попадется
            # файл с нестандартной кодировкой (заменит битые символы на '?')
            with open(py_file, 'r', encoding='utf-8', errors='replace') as in_f:
                content = in_f.read()
                out_f.write(content)

            # Добавляем отступы между файлами
            out_f.write("\n\n")

    print(f"Готово! Содержимое {len(py_files)} файлов агрегировано в '{output_file.name}'.")


if __name__ == '__main__':
    collect_python_contents()