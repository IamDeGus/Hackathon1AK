from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


main_menu = InlineKeyboardMarkup(inline_keyboard=[
  [InlineKeyboardButton(text="📈 Статистика", callback_data="stats_menu")],
  [InlineKeyboardButton(text="📹 Трансляция (Нет)", callback_data="stream_menu")],
	[InlineKeyboardButton(text="⚙️ Настройки (Нет)", callback_data="pass")]
])

stats_menu = InlineKeyboardMarkup(inline_keyboard=[
	[InlineKeyboardButton(text="📃 Количество этикеток", callback_data="show_label_count")],
	[InlineKeyboardButton(text="📦 Количество аккумуляторов", callback_data="show_count")],
  [InlineKeyboardButton(text="🚀 Скорость", callback_data="speed_menu")],
  [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
])

stream_menu = InlineKeyboardMarkup(inline_keyboard=[
  [InlineKeyboardButton(text="▶️ Начать трансляцию", callback_data="start_stream")],
  [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
])

speed_stats = InlineKeyboardMarkup(inline_keyboard=[
	[
		InlineKeyboardButton(text="⏱ 10 мин", callback_data="graph_10"),
		InlineKeyboardButton(text="⏱ 30 мин", callback_data="graph_30"),
		InlineKeyboardButton(text="⏱ 1 час", callback_data="graph_60"),
	],
	[
		InlineKeyboardButton(text="⏱ 5 час", callback_data="graph_300"),
		InlineKeyboardButton(text="⏱ 10 час", callback_data="graph_600"),
	],
	[
		InlineKeyboardButton(text="📄 Скачать Excel", callback_data="download_excel"),
	],
	[
		InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")
	]
])

input_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📥 Загрузить новый файл", callback_data="upload_excel")],
    [InlineKeyboardButton(text="📤 Текущий файл", callback_data="get_current_excel")],
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
])

label_menu = InlineKeyboardMarkup(inline_keyboard=[
	[
		InlineKeyboardButton(text="✏️ тип А ", callback_data="editA"),
		InlineKeyboardButton(text="✏️ тип В ", callback_data="editB"),
		InlineKeyboardButton(text="✏️ тип С ", callback_data="editC"),
	],
	[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_label_count")],
	[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")]
])