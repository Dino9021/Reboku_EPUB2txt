# Reboku EPUB2txt

把 EPUB 電子書轉成「在記事本裡讀起來舒服、閱讀器也能提供良好的體驗，同時還能大幅縮小體積」
的純文字書。單一 Python 檔、零必要相依、附命令列與圖形介面。

Convert EPUB books into plain-text books that read cleanly in Notepad, still give a
reader something good to work with, and take up a fraction of the space. One Python
file, no required dependencies, with both a command line and a window.

![授權 / License](https://img.shields.io/badge/license-GPL--3.0-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)

---

## 目錄 | Contents

- [這是什麼 | What it is](#這是什麼--what-it-is)
- [安裝與執行 | Install and run](#安裝與執行--install-and-run)
- [命令列 | Command line](#命令列--command-line)
- [圖形介面 | The window](#圖形介面--the-window)
- [輸出格式 RTB-1 | The RTB-1 output format](#輸出格式-rtb-1--the-rtb-1-output-format)
  - [1. 表頭 | The header](#1-表頭--the-header)
  - [2. 換行 = 換段 | A line break is a paragraph break](#2-換行--換段空行--真的空一行--a-line-break-is-a-paragraph-break-a-blank-line-is-a-blank-line)
  - [2b. 章內的小標題 | Sub-headings inside a chapter](#2b-章內的小標題--sub-headings-inside-a-chapter)
  - [3. 章節標記 | The chapter fence](#3-章節標記--the-chapter-fence)
  - [4. 目次區塊 | The Contents block](#4---目次-選用給人看的-the-contents-block-optional)
  - [5. 封面區塊 | The cover block](#5-封面區塊--the-cover-block)
  - [6. 超連結與畫線 | Links and drawn rules](#6-超連結與畫線--links-and-drawn-rules)
  - [6b. 註解 | Footnotes](#6b-註解--footnotes)
  - [7. 編碼 | Encoding](#7-編碼--encoding)
- [範例檔 | The sample pair](#範例檔--the-sample-pair)
- [圖片型書籍的判定 | How picture books are detected](#圖片型書籍的判定--how-picture-books-are-detected)
- [程式架構 | Architecture](#程式架構--architecture)
- [自己建置 .exe | Building the .exe yourself](#自己建置-exe--building-the-exe-yourself)
- [測試 | Tests](#測試--tests)
- [授權 | License](#授權--license)

---

## 這是什麼 | What it is

一本 EPUB 是一包 zip：裡面有 OPF 清單、閱讀順序（spine）、目次（NCX 或 nav），以及一堆
XHTML。這隻程式把那些讀出來，重新寫成一個 `.txt`：書籍資訊寫在最前面幾行、章節用
`--==# 標題 #==--` 標出層級、封面縮圖以 base64 夾在最後。結果用記事本打開仍然是一本
讀得下去的書；用支援本格式的閱讀器打開，書名、作者、系列、階層目次、章節跳轉、封面
全部都在。

An EPUB is a zip holding an OPF manifest, a reading order (the spine), a table of
contents (NCX or nav) and a pile of XHTML. This program reads those and rewrites them
as one `.txt`: book metadata on the first few lines, chapters fenced as
`--==# Title #==--` with the depth encoded in the fence, and the cover thumbnail
base64'd at the end. The result is still a readable book in Notepad; in a reader that
knows the format, the title, authors, series, nested TOC, chapter jumps and cover all
come back.

**體積 | Size.** 內文插圖、字型、樣式表都不會跟過來，所以檔案通常小得多：把一個 123 本的
書庫轉過去，**419 MB 變成 44 MB**（約九分之一；單本的中位數是剩 14%，圖最多的那本只剩
0.7%）。**例外是純文字的長篇小說**——EPUB 本身是壓縮過的 zip，而 `.txt` 沒有壓縮，所以
沒有插圖的大部頭反而會變成兩倍左右。要的是「一個檔案、到哪都讀得
開、順便省空間」的話，這筆交易在多數書上很划算。

Images, fonts and stylesheets do not come along, so the file is usually far smaller:
converting a 123-book library turned **419 MB into 44 MB** (about a ninth; the median
book keeps 14%, the most image-heavy one 0.7%). **The exception is a plain long novel** —
an EPUB is a compressed zip and a `.txt` is not, so an illustration-free doorstopper can
come out roughly twice the size.

**特點 | Highlights**

- **一個段落一行** —— 從區塊元素取字，句子不會被 `<span>` 之類的行內標籤切斷，`<rt>` 注音
  也不會混進正文。
  **One paragraph per line** — text is taken per block element, so inline tags never
  chop a sentence in half and `<rt>` ruby annotations never land mid-word.
- **目次照原書** —— 層級來自 EPUB 自己的 nav / NCX，不猜、不虛構。目次項目指向同一份文件
  裡的錨點時會正確切開。
  **The TOC is the book's own** — depth comes from the EPUB's nav/NCX, never guessed.
  Several TOC entries pointing into one document are split at their anchors.
- **每一段首行都縮排** —— 中日文書縮兩個全形空白（來源 EPUB 的縮排本來就寫在內文裡，照樣還給你），
  其他語言縮四個半形空白（同樣的視覺寬度，檔案維持純 ASCII）。這個格式用換行分段，所以縮排就是
  「這裡是新的一段」的記號，記事本與其他 TXT 閱讀器看起來才像一本正常的書。
  **Every paragraph is indented** — two ideographic spaces for Chinese and Japanese (their
  EPUBs carry the indent in the text itself, so it is written back), four spaces for everything
  else. A paragraph break is a line break in this format, so the indent is what shows where a
  paragraph starts.
- **章內的小標題自己一行** —— 一級章名以下的小標題以前會變成一般段落，讀起來像下一段黏了一句話。現在它**獨立一行、不縮排、
  前後各空一行**；原書自己畫了框的，前後改成**一行 20 個 `=`**（`=` 的外側再各空一行）。判定看
  兩件事：原書用了 `<h1>`–`<h6>` 而那個標題沒被章名用掉，或整行文字都來自同一段樣式而樣式表在
  它任一邊畫了線，或它是**這份文件的第一行**而整行都被設得更大更粗 —— 三者都是「有或沒有」，
  不猜比例（第 3 條為什麼一定要綁在「第一行」，見 [2b](#2b-章內的小標題--sub-headings-inside-a-chapter)）。
  章節標記已經寫過的標題不會再印一次。
  **A sub-heading gets its own line** — the headings under a chapter title used to come out as
  ordinary paragraphs. Now each stands alone, **un-indented**, one blank line either side; when
  the book drew a box round it, those blank lines become a row of twenty `=` (with a blank line
  outside each). Three yes-or-no signals decide it, and a heading the chapter marker already
  repeats is not printed twice.
- **原書的註解會標出來** —— 內文裡寫成 `(註[2])`、註解本身寫成 `註[2]: 內容`，以前參照只剩一個
  孤零零的數字。判定完全照 **EPUB 3 標準自己的詞彙**（`epub:type="footnote"`、`noteref`、
  `role="doc-backlink"`），沒有宣告的參照就看「它指向的是不是一個註解」；號碼取書自己印的那個字，
  不重新編號。
  **Footnotes are marked out** — `(註[2])` in the text, `註[2]: …` for the note itself, where a
  bare number used to sit looking like a stray character. Recognition is entirely by the
  **EPUB 3 / DPUB-ARIA vocabulary**; a reference that declares nothing is recognised by pointing
  at a note, and the number is the one the book printed.
- **目次項目不會因為那一頁是圖而消失** —— 掃描頁、圖版沒有可抽取的文字，它的目次項目會**往後**
  落在下一個有文字的頁面上（幾個標籤落在同一頁是正常的），而不是連標題一起丟掉。
  **A TOC entry never disappears because its page is a picture** — an entry pointing at a plate
  or a scanned page lands on the next page that has text instead of being dropped; several
  labels can share one page, which is fine.
- **書留白的兩種寫法都讀得懂** —— 空的段落，以及**樣式表**：引文、詩、註腳常常是靠換字型或多給
  一點上下間距隔開的。跟這本書自己的正常段落比，看得出是獨立的一塊就在它前面空一行。
  **Both ways a book asks for space are heard** — an empty paragraph, and the stylesheet:
  a quotation or a verse set in another font, or given a wider margin than this book's
  ordinary paragraph, gets a blank line in front of it.
- **書畫的線也畫得出來** —— `<hr>`，以及用**上下框線**圍起來的區塊（很多書把引文或注解框起來，
  畫面上跟 `<hr>` 一樣），都輸出成一行 20 個 `-`。
  **The lines a book draws come across** — both `<hr>` and a block fenced by a top/bottom
  border become a row of twenty hyphens.
- **對外的超連結會寫進文字裡** —— `<https://…>`、`<mailto:…>` 接在它所屬的文字後面，角括號讓人
  與程式都看得出網址到哪裡結束。書內的註腳連結不寫（`.txt` 追不過去，寫了只會吵）。
  **Outbound links are written into the text** — `<https://…>` right after the words it belongs
  to; the angle brackets are what tell a person *and* a program where the address ends.
  In-book navigation is not written (a text file cannot follow it).
- **封面帶得走** —— 等比例縮到 200×300 以內的 JPEG，base64 寫在檔尾。
  **The cover survives** — a JPEG fitted inside 200×300, base64 at the end of the file.
- **漫畫直接略過** —— 一頁一圖的書沒有可抽取的文字，整批檢查完一次列出，不會產生一堆空檔。
  **Picture books are skipped** — one-image-per-page books hold no text; they are
  checked as a batch and listed once instead of becoming near-empty files.
- **零必要相依** —— 只用標準函式庫（`zipfile` / `xml.etree` / `html.parser` / `tkinter`）。
  Pillow 只有「要封面」時才需要。
  **No required dependencies** — standard library only. Pillow is needed for covers only.

---

## 安裝與執行 | Install and run

### 方式一：直接下載 .exe（Windows，不需安裝 Python）

到 [Releases](../../releases) 下載 `EPUB2txt.exe`，複製到任何一台 Windows 電腦就能用。
不需要 Python、不需要 Pillow、不需要任何執行環境。

Download `EPUB2txt.exe` from [Releases](../../releases) and copy it anywhere. No
Python, no Pillow, no runtime of any kind is needed on that machine.

### 方式二：跑原始碼

需要 Python 3.8 以上。

```bash
git clone https://github.com/Dino9021/Reboku_EPUB2txt.git
cd Reboku_EPUB2txt

# 可選：要夾帶封面才需要 / optional, only if you want covers embedded
pip install -r requirements.txt

python EPUB2txt.py            # 開視窗 / opens the window
python EPUB2txt.py book.epub  # 直接轉一本 / convert one book
```

沒裝 Pillow 也能跑，只是每本書的表頭會寫 `Cover: False`，程式會在命令列與狀態列各說一次原因。
Without Pillow everything still works; every book just declares `Cover: False`, and the
program says why once.

---

## 命令列 | Command line

```
python EPUB2txt.py [來源] [-o 輸出資料夾] [-r] [-f] [--flat] [--no-cover]
```

| 參數 / Option | 作用 / What it does |
|---|---|
| `來源` / `source` | `.epub` 檔或一整個資料夾，自動判斷。**不給就開視窗。** An `.epub` file or a folder; omit to open the window. |
| `-o`, `--output` | 輸出資料夾。不給就寫在每本書旁邊。Output folder; default is beside each book. |
| `-r`, `--recurse` | 連子資料夾一起找。Also convert books in sub-folders. |
| `-f`, `--force` | 直接覆寫。不加時，遇到已存在的檔會一個一個問。Overwrite; otherwise it asks per file. |
| `--flat` | 全部 `.txt` 直接放進 `-o`，不重建來源的子資料夾結構。Flat output, no sub-folders. |
| `--no-cover` | 不夾帶封面，表頭寫 `Cover: False`。No cover block. |
| `--gui` | 帶了來源仍然開視窗。Open the window even with a source given. |
| `--self-test` | 跑內建檢查後結束。Run the built-in checks and exit. |

**輸出檔名一律與來源同名**：`book.epub` → `book.txt`。
The output is always named after the source file.

```bash
# 一整個書庫，照原本的資料夾結構輸出到 D:\txt
python EPUB2txt.py C:\books -r -o D:\txt

# 同上，但全部攤平成一層
python EPUB2txt.py C:\books -r -o D:\txt --flat

# 遇到已存在的檔一律覆寫，不要問
python EPUB2txt.py C:\books -r -o D:\txt -f
```

沒人在鍵盤前（管線、排程）而又沒加 `-f` 時，**一律保留既有檔**、絕不無聲覆寫，結尾會列出被保留的數量。
When nothing can answer the prompt (a pipe, a scheduled run) and `-f` was not given,
existing files are always kept — never silently overwritten.

---

## 圖形介面 | The window

不帶參數執行就會開啟。左邊是來源、右邊是佇列、下面是即時狀態，像 FTP 用戶端那樣。

Run it with no arguments. Sources on the left, the transfer queue on the right, a live
log across the bottom.

**介面語言**：跟著**作業系統的顯示語言** —— 系統是中文就開中文，其他語言一律開英文。右上角的
「語言」可以自己切換，選了會記住（切換時視窗會重開一次，所以請在開始轉換前切；轉換進行中不會讓你切）。

**Language**: the window follows the **operating system's display language** — Chinese if the
system is set to Chinese, English for everything else. The `Language` box at the top right
switches it and the choice is remembered. Switching reopens the window, so do it before you
start converting (it is refused while a conversion is running).

```
┌──────────────────────────────────────────────────────────────┐
│ 來源 [C:\books..............................] [瀏覽][重新整理] │
│ 輸出 [D:\txt.................................] [瀏覽]        │
│      ☐ 與來源同資料夾  ☑ 複製來源資料夾結構  ☑ 包含書籍封面圖片  │
├───────────────────────────┬───┬──────────────────────────────┤
│ 來源清單(勾選要轉換的書)    │   │ 轉換佇列                      │
│ [-] books                 │加入│ book1.epub  D:\txt\book1.txt │
│   [v] 小說                 │ → │             完成              │
│     [v] book1.epub  1.2 MB│   │ book2.epub  D:\txt\book2.txt │
│   [ ] 漫畫                 │移除│             轉換中…           │
├───────────────────────────┴───┴──────────────────────────────┤
│ [開始轉換] [停止]  ███████░░░░░  3 / 12                       │
├──────────────────────────────────────────────────────────────┤
│ 執行狀態                                                      │
│ 15:04:12  book1.epub -> book1.txt                            │
│ 15:04:12    OK  book1.txt  某本書 (45,102 chars)              │
└──────────────────────────────────────────────────────────────┘
```

- 左邊是檔案總管式的樹狀清單，**只列出資料夾與 `.epub`**。點一列就切換勾選，展開箭頭維持
  原本開合功能。資料夾有三種狀態：底下全勾 `[v]`、只勾一部分 `[-]`、都沒勾 `[ ]`。
  勾一個資料夾等於勾下面所有的書。子資料夾**展開時才載入**，所以指向一整顆硬碟也不會卡住。
- 轉換跑在背景執行緒，視窗不會凍住；「停止」在書與書之間生效，不會留下半截檔案。
- 目的檔已存在時跳一個對話框問「是／否／全部是／全部否」，選了「全部」這一批就不再問。
- 右邊佇列雙擊已完成的項目，會用系統預設程式打開那個 `.txt`。
- 視窗關閉時記住當前資料夾與三個選項，下次開啟直接回到原位。第一次開啟預設從 `C:\` 開始、
  輸出到使用者的「文件」資料夾。

The left pane is an explorer-style tree listing folders and `.epub` files only; clicking
a row toggles its tick box, and a folder shows all `[v]` / partial `[-]` / none `[ ]`.
Ticking a folder ticks every book under it. Children load lazily on expand. Conversion
runs on a worker thread, Stop takes effect between books, overwrites are asked once per
batch with a yes/no/all/none dialog, and the window remembers where it was left.

---

## 輸出格式 RTB-1 | The RTB-1 output format

下面的例子直接取自 [`samples/Sample.txt`](samples/Sample.txt) —— 那是把 [`samples/Sample.epub`](samples/Sample.epub)
丟給這隻程式轉出來的結果,你可以自己重跑一次比對(見[範例檔](#範例檔--the-sample-pair))。

The example below is taken straight from [`samples/Sample.txt`](samples/Sample.txt), which
is what this program produces from [`samples/Sample.epub`](samples/Sample.epub) — you can
rerun it and compare (see [the sample pair](#範例檔--the-sample-pair)).

```
Reboku Text Book 1
Title: Aesop's Fables: A Selection
Author: Aesop
Language: en
Cover: True

--==# Contents #==--
Aesop's Fables: A Selection
Table of Contents
Introduction
The Fox and the Grapes
…

--==# Introduction #==--

    Aesop is an ancient teller of short tales, and this little book gathers ten of the most beloved ones.
    In these pages you will meet clever foxes, proud lions, a patient tortoise, and a boastful hare. Each animal learns something the hard way.
    Every tale is short, and every tale ends with a moral, so the lesson stays with you long after the story is done.

--==# The Fox and the Grapes #==--

    One warm afternoon a hungry fox trotted through an orchard and spotted a bunch of ripe grapes hanging high on a vine. The fox licked his lips, for the fruit looked sweet and juicy.
    …
    Moral: It is easy to despise what you cannot have.

--==[ Cover ]==--
/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL
DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/
--==[ /Cover ]==--
```

### 1. 表頭 | The header

檔案最前面，一行一個 `欄位: 值`，**英文欄位名、半形冒號**，到**第一個空行**為止。

One `Field: value` per line at the top of the file, English field names, ASCII colon,
ending at the first blank line.

| 欄位 / Field | 意思 / Meaning |
|---|---|
| `Reboku Text Book 1` | 格式宣告，放**第一行**（沒有冒號）。寫了它，讀不懂的新欄位會被略過而不是整段作廢。 Format declaration on line 1. With it present, a field a reader does not know is skipped instead of invalidating the whole header. |
| `Title` | 書名。沒寫就用檔名。 Title; falls back to the file name. |
| `Author` | 作者。多位作者寫多行。 One line per author. |
| `Publisher` | 出版社 / Publisher |
| `Date` | 出版日期或年份 / Publication date or year |
| `Language` | 語言標籤，如 `zh-TW`、`ja`、`en` / BCP-47-ish language tag |
| `Series` | 系列名稱 / Series name |
| `Series Index` | 系列中的第幾本 / Position in the series |
| `Cover` | `True` 或 `False` —— 檔尾有沒有封面區塊。**一定會寫**，所以解析器不必掃到檔尾才知道。 `True` or `False`, always written, so a parser never has to read to the end of the file to find out. |

### 2. 換行 = 換段，空行 = 真的空一行 | A line break is a paragraph break; a blank line is a blank line

**一行就是一段**，段落之間**不空行**，每一段的**首行縮排**（中日文兩個全形空白、其他語言四個
半形空白）—— 換行負責分段，縮排負責讓人看出來。**空行只代表原書真的留白**（引文前後、小標前後
那種）：原書空一個段落就輸出一個空行，連續幾個就幾個，本程式不合併。

書留白有兩種寫法，兩種都會被讀出來：

1. **空的段落**（`<p>&nbsp;</p>`）—— 一個空段落一個空行。
2. **樣式表**（`<p class="quote">` 配上 `margin-top:21px`，或換一種字型）—— 這一段在頁面上
   本來就是獨立的一塊。判斷方式是**跟這本書自己的正常段落比**：**字型變了**，或**上下的間距
   比這本書慣用的間距多出半行以上**，就在**這一段前面**放一個空行。

   只放前面、不放後面：換回原本樣式的下一段自己會放它那一行，所以區塊的兩邊各一行，不會變成
   兩行。兩個理由同時成立時也只放一行，那個位置本來就有空行時也不再加。

   > 每本書自己校準，所以「每一段都給 margin」的書一行都不會多。讀不到或看不懂的樣式表一律
   > 當作沒有宣告 —— 最壞的情況就是回到只認第 1 種寫法，不會動到文字。

> **為什麼不是「空行分段」**：那樣每一段都要賠上一行空白，實測同一本書 5,492 行裡有 3,121 行
> 是空的，記事本裡鬆得不像一本書；更關鍵的是，空行一旦拿去當分隔符，**原書「這裡要空一行」
> 就沒有寫法可用了**。
>
**One line is one paragraph**, with no blank line between paragraphs, and **every paragraph
opens with an indent** (two ideographic spaces for CJK, four spaces otherwise) — the line
break makes the paragraph, the indent makes it visible. A blank line means only one thing:
**the source book left real space there** — one empty paragraph in the EPUB becomes one blank
line, and runs are never merged.

> **Why not "a blank line separates paragraphs"?** It spends one blank line per paragraph —
> measured on a real book, 3,121 of 5,492 lines were blank, which reads far too loose in
> Notepad — and it takes the blank line away from books that genuinely want one.
>
章節標記 `--==# 標題 #==--`、目次區塊與封面區塊**前後各留一個空行**，那是結構，解析器不會
把它畫成留白。
A blank line on each side of a chapter fence, the contents block and the cover block is
**structure**: a reader does not draw it as space.

> **⚠️ 縮排是語意，不是排版**：因為每一段都有縮排，**沒有縮排的一行就是小標題**（見下一節）。
> 自己手寫這個格式的話，內文段落一定要縮排，不然每一段都會被讀成標題。
> **⚠️ The indent is meaning, not decoration**: because every paragraph carries one, **a line
> without one is a sub-heading** (next section). Hand-writing this format? Indent your
> paragraphs, or every one of them reads as a heading.

### 2b. 章內的小標題 | Sub-headings inside a chapter

原書在章名底下的小標題，輸出成**獨立一行、不縮排、前後各空一行**：

```
　　…前一段的最後一句。

小標題

　　接下來的內文…
```

**原書自己畫了框的**小標題（例如用左右虛線把標題框住），前後那兩個空行改成**一行 20 個 `=`**，
`=` 的外側再各空一行 —— 純文字讀起來才不擁擠：

```
　　…前一段的最後一句。

====================
加了外框的小標題
====================

　　接下來的內文…
```

判定靠三個訊號，每一個都是「有或沒有」，不量比例、不設門檻：

1. 原書用了 `<h1>`–`<h6>`，而那個標題沒有被章名用掉。
2. 整行文字都來自**同一段行內樣式**，而樣式表在它**任何一邊**畫了線（例如
   `border-style: none dashed` —— 橫排時是文字兩端各一條虛線，直排時就變成上下）。
3. **這份文件的第一行文字**，而且整行都由樣式表設得比內文更大或更粗的片段組成。

**第 3 條為什麼一定要綁在「第一行」**：很多書把**古文引文**設成跟標題同一組放大粗體字。
拿掉「第一行」這個限制，在 137 本書的測試書庫上會有 **940 行**被誤判成標題 —— 古典詩、
禮儀典籍的段落、81 字的英文散文、92 字的純內文。限定在第一行之後是 **137 行 / 6 本，逐一
看過 0 誤判**，因為引文永遠不會是一章的開頭。

「整行」這個條件也是刻意的：句子中間的樣式片段是**強調**不是標題，包起來會把一句話切成三段。

**書在章首把章名再印一次時不重複輸出**：章節標記已經寫了「法則01　某某標題」，頁面又印
一次短版「某某標題」—— 這種小標題整行丟掉。比對是**去空白後的精確包含**，所以標記寫
「〈某篇〉：副標題」而頁面寫「〈某篇〉──副標題」不算重印（那是書自己的
副標，兩者確實不同）。

Three yes-or-no signals decide it: an `<h1>`–`<h6>` the chapter title did not use up; a whole line
made of a **single inline run** that the stylesheet borders on **any** side; or **the first line of
the document**, when the runs that make it up account for all of it and the stylesheet sets any of
them bigger or bolder. That third one MUST stay tied to the first line — "bigger or bolder" alone
called **940 lines** across the 137-book test library headings, most of them classical quotations
set in the very same face; tied to the first line it is **137 lines across 6 books with no false
positives**, because a quotation is never the first thing in a chapter. A heading the chapter
marker already repeats (exact containment on whitespace-stripped text) is dropped rather than
printed twice.

A sub-heading under a chapter title becomes **its own un-indented line with one blank line on
each side**; when the book drew a **box** round it, those blank lines become a row of twenty `=`
(with a blank line outside each, so it does not read as crowded). Two yes-or-no signals decide
it: an `<h1>`–`<h6>` the chapter title did not use up, or a whole line made of a **single inline
run** that the stylesheet borders on **any** side. The "whole line" condition is deliberate — a
styled run in mid-sentence is emphasis, not a heading, and boxing it would cut the sentence in
three.

### 3. 章節標記 | The chapter fence

```
--==# 第一部 #==--             ← 第一層 / level 1
--==## 兩個嬰兒的誕生 ##==--    ← 第二層 / level 2
--==### 更深一層 ###==--        ← 第三層，最多六層 / level 3, up to six
```

- **`#` 的數量就是目次層級**，前後要一樣多。
  The number of `#` IS the TOC depth, and the two runs must match.
- 標記**必須從該行第 0 欄開始**、整行只有這個標記。前面多一個空白就是普通內文 ——
  這正好是**逃脫寫法**：萬一內文本身長得像標記，縮排一格即可（本程式會自動這樣做）。
  The fence must start at column 0. One leading space makes it body text, which is
  exactly the escape hatch — and the converter applies it automatically.
- 只有標記、沒有內文的章節就是**分部標題**，很正常。
  A fence with no text under it is a part divider, which is normal.

圍籬故意設計成這種少見的樣子：真實的標題或內文可能以 `=`、`#`、`*` 開頭結尾，但不可能
剛好是 `--==#` … `#==--`。

### 4. `--==# 目次 #==--`（選用，給人看的）| The Contents block (optional)

想在記事本裡一眼看到全書目次就放這一段：標題寫 `Contents`（或 `目次`、`目錄`、`TOC`），
下面一行一個章節、每層縮排兩格。**解析器會跳過這一段** —— 真正的目次是從章節標記算出來的，
所以這份清單怎麼寫都不會讓目次跑掉。本程式只列出**實際寫出來的**章節，不會出現「清單有、
書裡沒有」的矛盾。

A human-readable contents listing. A parser skips it — the real TOC is derived from the
chapter fences — so it can never disagree with the book. This converter builds it from
the sections it actually wrote.

### 5. 封面區塊 | The cover block

```
--==[ Cover ]==--
<base64，每 76 字元一行>
--==[ /Cover ]==--
```

- 放在檔案**最尾端**，內容是一張 **JPEG**，等比例縮到 **200×300 以內**（只縮不放）。
- 圍籬用 `--==[ … ]==--`，**不是**章節的 `--==# … #==--` —— 兩者不可能互相誤認。
- 解析器**在讀結構之前先把整個區塊切掉**（不然這幾百行會變成最後一章的內文）。base64 每
  76 字元換行、中間沒有空行，兩道圍籬之間的行接起來就是原本的 base64：`"".join(lines).strip()`。
- **區塊說了算**：表頭寫了 `Cover: True` 卻沒有區塊 = 沒有封面；沒寫 `Cover` 但有區塊 =
  照樣有封面。`Cover` 欄位是給「不想掃到檔尾」的解析器用的提示，不是事實來源。
- 不認得這個區塊的閱讀器（或記事本）會把它當成一段文字直接顯示出來。這是可接受的取捨：
  它是本格式特有的資訊，別的閱讀器本來就不會認識。

At the very end of the file: a JPEG fitted inside 200×300 keeping its aspect ratio,
base64'd, wrapped at 76 characters, fenced with `--==[ … ]==--` — deliberately *not*
the chapter fence, so neither can be mistaken for the other. A parser strips the whole
block **before** it looks at any structure (otherwise those hundreds of lines become the
last chapter's body); joining the lines between the fences gives the original base64
back. **The block decides, not the header**: `Cover: True` with no block means no cover,
and a block with no `Cover` line is still a cover. A reader that does not know the block
simply shows it as text, which is the accepted trade-off.

### 6. 超連結與畫線 | Links and drawn rules

原書的**對外**超連結（`http`／`https`／`mailto`／`ftp`／`tel`）寫在它所屬的文字後面，空一格，
網址用**角括號**包起來：

```
　　ＦＢ：插畫家 <https://www.facebook.com/example/>
　　資料來源出自 荷蘭航海食物 <http://www.historien.nl/scheepsvoedsel/> ，2020 年查閱。
```

- **為什麼要角括號**：網址後面常常直接接標點（`，`、`）`、`。`），沒有結束記號的話，人跟程式都
  不知道網址到哪裡為止。角括號是純文字界處理這件事的老規矩。
- **連結掛在圖示上**（常見的 FB／IG 小圖）本身沒有文字，網址就**自己站一行**——原書那一頁本來
  就是「一行字，下面一個可以點的圖示」。
- **連結文字本身就是網址**時只寫一次（`<https://www.x.com/y/>`），不會重複。
- **同一個網址在上一行已經出現過**（出版社常常放一個文字連結再放一個同樣連結的圖示）就不再寫第二次。
- **書內的連結不寫**：註腳、目次那些相對路徑，`.txt` 追不過去，寫進去只會吵。
- **網址先掃過再寫**：拿掉追蹤參數（`utm_*`、`fbclid`、`gclid`、`igshid`、`pk_*`…）與介面語言
  參數（`hl`、`lang`、`locale`…）。**其餘查詢參數一律保留** —— 搜尋條件、頁碼、檔案 id 常常
  就是網址本身，砍掉連結就壞了。留下來的參數維持原本的編碼，不重新編碼。
  `mailto:` 的查詢（`?subject=`、`?body=`）不是位址而是寫信視窗的預設值，整段拿掉。

Outbound links only (`http`/`https`/`mailto`/`ftp`/`tel`), one space after the text they belong
to, the address in **angle brackets** — a URL runs straight into the next character, so without
a closing mark neither a reader nor a program can tell where it ended. A link whose content is a
picture has no text of its own, so its address stands on its own line; a link whose text already
*is* its address is written once; and an address that already appears on the line above (a text
link plus its icon) is not repeated. In-book hrefs are never written — a text file cannot follow them.
Addresses are swept before they are written: tracking parameters (`utm_*`, `fbclid`, `gclid`,
`igshid`, `pk_*`, …) and interface-language ones (`hl`, `lang`, `locale`, …) are dropped, and
**every other query parameter is kept** — a search, a page number or a file id often *is* the
address, and surviving parameters keep their original encoding.

**原書畫的線**——輸出成**連續 20 個 `-`**，前面照樣有段落縮排。兩種來源都認：`<hr>`，以及
**上下有框線的區塊**（很多書把引文或注解用一個框圍起來，畫面上跟 `<hr>` 一模一樣；`border:`
單獨寫就是一個框，上下各一條）。表格的儲存格框線不算；兩條線不會相鄰；線的前後**最多各空一行**
（線本身就是分隔，空兩行只會讓它浮在洞中間）。

```
　　--------------------
```

（縮排也讓它不會落在第 0 欄，那裡的一排 `-` 是表頭的結束線。）
A `<hr>` becomes twenty hyphens, carrying the paragraph indent like any other line — which also
keeps it off column 0, where a run of dashes is the header block's closing rule.

### 6b. 註解 | Footnotes

原書的註解會標出來 —— 以前內文裡只剩一個孤零零的數字，看起來像多餘的字：

```
　　「飲食定量分配，一日兩餐。」(註[2])抗戰勝利後，成都市民分成兩派。

　　--------------------
　　註[2]: 參見《某書》
```

判定**完全照 EPUB 3 標準自己的詞彙**，沒有一處靠猜：

| 東西 | 標準怎麼說 |
|---|---|
| 註解本體 | `epub:type="footnote"`／`endnote`／`rearnote`，或 `role="doc-footnote"`／`doc-endnote` |
| 內文參照 | `epub:type="noteref"`、`role="doc-noteref"`、`rel="footnote"` |
| 回跳連結 | `role="doc-backlink"`，或註解裡指回內文的內部連結 |

**沒有宣告參照的書怎麼辦**：測試書庫裡 6 本有註解的書只有 1 本連參照都宣告，另 4 本的參照是
普通的內部連結 —— 那就看**它指向的是不是一個註解**。523/526 條註解可以這樣解析；剩下 3 條
文中根本沒有參照，原封不動。

號碼**取書自己印在那個位置的字**（`1`、`註1`、`1.`），不自己重新編號，讀者才對得上紙本。
id 對應**先掃完整本書**再開始寫檔，因為有些書把註解放在引用它的**下一章**。「註」字依書籍
語言選：中文 `註`／`注`、日文 `注`、韓文 `주`、其他 `Note`。註解裡指回內文的箭頭（`↺`）在
純文字裡沒有東西可指，直接拿掉。

Footnotes are recognised entirely through the **EPUB 3 / DPUB-ARIA vocabulary** — nothing is
guessed. A reference that declares nothing is recognised by pointing AT a note, which is how four
of the six books with notes in the test library work. The number is the one the book printed
there, never renumbered; ids are indexed across the whole book first, because some books put a
note in the chapter after the one citing it; and the word follows the book's language.

### 7. 編碼 | Encoding

**UTF-8 with BOM**。BOM 讓記事本在任何 Windows 版本上都能正確顯示中日韓文字，也讓解析器
不必用猜的。換行 CRLF/LF 都可以。

UTF-8 with a BOM: it makes Notepad show CJK correctly on every Windows build, and it
turns encoding detection into a declaration rather than a guess.

---

## 範例檔 | The sample pair

[`samples/`](samples/) 裡有一組對照：

| 檔案 | 內容 |
|---|---|
| [`Sample.epub`](samples/Sample.epub) | 一本小小的 EPUB：《伊索寓言》選十則，含封面圖 |
| [`Sample.txt`](samples/Sample.txt) | **就是把上面那個檔丟給這隻程式轉出來的結果** |

所以它同時是格式範例、也是一個可以自己重跑的檢查：

```bash
python EPUB2txt.py samples/Sample.epub -o /tmp/out
# 產出的 /tmp/out/Sample.txt 會與 samples/Sample.txt 完全一致(逐位元組)
```

兩個檔案都是為了測試而寫的伊索寓言改寫本，**沒有版權問題**，可以自由取用、修改、
拿去當你自己的格式範本。

`samples/` holds a matched pair: a small EPUB (ten of Aesop's fables, with a cover) and
exactly what this program produces from it. That makes it both the format example and a
check you can rerun yourself — the output is byte-for-byte identical to the committed
`Sample.txt`. Both files are a retelling written for testing and carry **no copyright
restrictions**; use or modify them freely.

---

## 圖片型書籍的判定 | How picture books are detected

漫畫、掃描書是「一頁一張圖」，裡面沒有可抽取的文字，硬轉只會得到一堆空檔。這裡**真的逐頁算**，
不是憑書名或大小猜：

Comics and scanned books are one picture per page and hold no extractable text.
The verdict is counted page by page, never guessed:

1. **單圖頁**＝這一頁**恰好** 1 個圖片參照（`<img>` 或 SVG `<image>`）**且**可見文字 < 100 字。
   可見文字＝去掉 `<head>` / `<style>` / `<script>` / 所有標籤 / HTML 實體之後，不計空白的字元數
   （所以 `alt`、路徑這些屬性文字不算）。
   A **single-image page** holds exactly one image reference and fewer than 100 visible
   characters — visible meaning after `<head>`/`<style>`/`<script>`, all tags and all
   entities are removed, whitespace not counted (so `alt` text and paths never count).
2. **整本的判定**：
   - 版式書（OPF 宣告 `pre-paginated`）：**每一頁**都是單圖才算圖片書。有任何一頁是文字，
     它就是一本排版過的文字書。
   - 流式書：單圖頁 **≥ 3 頁**且佔 spine **≥ 70%**。
   - Fixed-layout: **every** page must be single-image. Reflowable: at least 3 such
     pages **and** at least 70% of the spine.
3. **超過 16 KB 的頁面不讀**：單圖包裝頁就是 XML 宣告 + head + 一個 `<img>`，典型 0.3–1.5 KB；
   16 KB 已是一個數量級的餘裕，更大的檔案在定義上不可能是單圖頁，直接算文字頁。大小取自
   zip 目錄，不解壓，所以問每一頁都不花錢。
   Entries over 16 KB are never read: a wrapper page is 0.3–1.5 KB, so anything bigger
   is a text page by definition. The size comes from the zip directory — no decompression.

門檻不是拍腦袋來的：實測一個真實書庫，圖片書落在 99% 以上、純文字書 7–18%，最難的一本
（54 頁裡夾了 74 張插圖的文字書）是 37%。70% 落在那 60 個百分點的空隙正中間。

判不出來的壞書一律當作文字書留在佇列裡，讓轉換階段回報真正的錯誤，不會無聲消失。
A book that cannot be judged is treated as text so the converter reports the real error
instead of the book vanishing silently.

---

## 程式架構 | Architecture

單一檔案 `EPUB2txt.py`，由上而下分成幾段，每段只依賴它上面的：

One file, in sections, each depending only on the ones above it:

| 段落 / Section | 內容 / What lives there |
|---|---|
| **small helpers** | 命名空間無關的標籤比對、空白壓縮、zip 路徑解析。`_parse_xml` 會**拒絕宣告實體的 XML** —— XXE 與 billion-laughs 都需要實體宣告，而真實 EPUB 的 OPF/NCX 不會有，所以擋掉這兩個洞又不必引入第三方 XML 套件。 Namespace-agnostic tag matching, whitespace collapsing, zip path resolution. `_parse_xml` **refuses XML that declares entities** — both XXE and billion-laughs need an entity declaration and no real EPUB has one, so this closes both holes without a third-party parser. |
| **HTML extraction** | `_BlockText`：XHTML → 一個區塊元素一行，並記下每個 `id` 錨點落在第幾行。`_NavParser` / `_ncx_entries`：EPUB3 nav 與 EPUB2 NCX → `(層級, href, 標題)`。 `_BlockText` turns XHTML into one line per block element plus where each id anchor landed; `_NavParser` / `_ncx_entries` read the EPUB3 nav and the EPUB2 NCX into `(depth, href, label)`. |
| **EPUB model** | `Epub` 類別：container.xml → OPF → 書籍資訊、manifest、spine、目次、封面。 The `Epub` class: container.xml → OPF → metadata, manifest, spine, TOC, cover. |
| **emitting** | `convert()`：走 spine、按目次切章、組出整份 `.txt`。順手略過封面頁、原書目次頁、與表頭重複的書名頁。 `convert()` walks the spine, splits at TOC anchors and assembles the whole `.txt`. |
| **the cover trailer** | `cover_jpeg_base64()` / `cover_block()`：封面 → 200×300 JPEG → base64 → 檔尾區塊。 Cover → thumbnail → base64 → the trailing block. |
| **job model** | `plan()` / `target_for()` / `convert_to()` / `OverwritePolicy` / `run()`。**命令列與圖形介面共用這一層**：`run()` 用回呼回報每一本的結果，所以兩邊的行為不可能不一致。 Shared by both front ends: `run()` reports every outcome through a callback, so the CLI and the GUI cannot drift apart. |
| **picture books** | `visible_text_length()` / `page_is_single_image()` / `image_book_verdict()` / `is_image_book()`。 |
| **CLI** | `main()`（argparse）、`_run_cli()`、主控台的覆寫詢問與回報。 |
| **GUI** | `_Gui`（tkinter）、覆寫對話框、視窗狀態的記憶。轉換跑在 worker thread，透過 `queue.Queue` 回報；要問使用者時把問題交回主執行緒、worker 等結果，因為 Tk 只能在單一執行緒上動。 The window; conversion runs on a worker thread and reports through a `queue.Queue`. A question is handed back to the main thread and the worker waits for the answer, because Tk is single-threaded. |
| **self-checks** | `--self-test`：命名規則、掃描、覆寫記憶、單圖頁判定、圍籬不衝突。 |

**沒有第三方相依**（Pillow 只在要封面時延遲載入），所以任何裝了 Python 3.8+ 的機器都跑得動。
No third-party dependency (Pillow is imported lazily, only for covers).

---

## 自己建置 .exe | Building the .exe yourself

Windows 上雙擊 `build-exe.bat` 就好。它會：找 Python → 裝好 `pyinstaller` 與 `pillow` →
先跑一次自我測試（不過就不建置）→ 打包 → **再用建好的 `.exe` 跑一次自我測試** →
清掉中間檔，留下 `dist\EPUB2txt.exe`。

Double-click `build-exe.bat`. It finds Python, installs `pyinstaller` and `pillow`,
runs the self-test (and refuses to build if it fails), packages, **re-runs the
self-test using the built `.exe`**, then cleans up, leaving `dist\EPUB2txt.exe`.

手動的話 | By hand:

```bash
pip install pyinstaller pillow
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name EPUB2txt --collect-submodules PIL EPUB2txt.py
```

- **圖示**：Releases 上的 `.exe` 帶著 Reboku 的圖示，但那張圖是品牌美術檔、**不在這個
  repo 裡**（本 repo 是 GPL-3.0，放進來等於連圖也一併授權出去）。`build-exe.bat` 因此把
  `--icon` 當成選用的：資料夾裡放了 `icon.ico` 就用它，沒有就用 PyInstaller 的預設圖示，
  程式本身完全一樣。想換成自己的圖示，把 `icon.ico` 放進來即可。
  **The icon** is brand artwork and is deliberately not in this repository (it is GPL-3.0
  here, which would license the image away too). `build-exe.bat` treats `--icon` as
  optional — drop your own `icon.ico` beside it, or build without one.
- `--onefile`：單一檔案，複製到任何一台 Windows 就能跑（第一次啟動會多花一兩秒解開）。
- `--windowed`：**完全不建立主控台**，所以雙擊時不會先閃一個黑框。命令列照樣能用 ——
  程式啟動時會用 `AttachConsole` 接上「叫它起來的那個終端機」再開啟標準輸出
  （`_use_parent_console`）。**不要改回 `--console`**：主控台是在 Python 啟動之前就由
  Windows 建立的，等程式跑起來再去藏它已經太晚，一定會閃。
- `--collect-submodules PIL`：封面編碼是在函式裡延遲載入的，這裡明講以免被相依掃描漏掉。

`--windowed` means Windows never creates a console, so a double-click never flashes a
black box. The command line still works because the program attaches to the terminal it
was started from. Do not switch back to `--console`: the console exists before Python
does, so hiding it from Python is always too late to prevent the flash.

**一個副作用**：視窗程式不會佔住命令列，所以從終端機執行時提示字元會**立刻回來**、輸出
隨後才出現。需要讓 shell 等它跑完（例如寫在批次檔裡），前面加 `start /wait`：

```
start "" /wait EPUB2txt.exe C:\books -r -o D:\txt
```

One side effect: a windowed program does not hold the shell, so your prompt returns
immediately and the output follows asynchronously. Prefix with `start "" /wait` when you
need the shell to wait — for example inside a batch file.

成品約 21 MB，包含 Python、Tcl/Tk 與 Pillow。
The result is about 21 MB and contains Python, Tcl/Tk and Pillow.

---

## 測試 | Tests

```bash
python EPUB2txt.py --self-test
```

不需要任何測試框架，不需要下載任何東西，跑完印一行 `self-test OK`。

檢查本身放在 `selftest.py`，是開發用的檔案，**不在發行檔裡** —— 發行的就是 `EPUB2txt.py`
這一個檔案。所以從 Releases 下載的 `.exe` 問它 `--self-test` 會直接告訴你檔案不在；`.exe` 的
建置改用另一個更適合它的驗收：讓它轉一次 `samples/Sample.epub`，輸出必須與凍結的
`samples/Sample.txt` **逐位元組相同** —— 那才抓得到「凍結成 exe」真正會弄壞的東西（漏掉的
延遲 import、失效的資源路徑、起不來的啟動殼）。

The checks live in `selftest.py`, a development file that is **not part of a release** — what
ships is `EPUB2txt.py` alone. The `.exe` from Releases says so if you ask it for `--self-test`;
its build gate is instead that it converts `samples/Sample.epub` to something
**byte-identical** to the frozen `samples/Sample.txt`, which is what actually catches a broken
freeze.

涵蓋：

- 輸出檔名規則、掃描與扁平／鏡射的路徑計算、覆寫記憶（是／否／全部是／全部否）
- 可見文字長度、單圖頁與整本圖片書的判定門檻（每一個案例都釘住）
- 段落縮排（中日文兩個全形／其他語言四個半形）、內文長得像圍籬時的逃脫
- 空行只在原書留白處出現、圍籬前後各一個空行、章首章尾不留空
- 書本自己的目錄頁不會被當成內文寫出來
- 超連結：接在文字後面、圖示連結自己一行、文字本身就是網址時只寫一次、書內連結不寫、
  追蹤與語言參數被清掉而其餘查詢參數原封保留
- 樣式表讀出來的留白：換字型、間距比本書慣用的多出半行；同一個 `<p>` 用 `<br>` 斷行的詩
  不會被當成兩段來比；每段都有 margin 的書一行都不會多
- 線:`<hr>` 與**上下框線的區塊**都畫成 20 個 `-`，縮排讓它不可能落在第 0 欄，兩條線不會
  相鄰（中間夾一張帶不走的圖也一樣），線的前後最多各一個空行
- 封面圍籬不會被誤認成章節標記，base64 接得回原本的字串
- **一支端到端檢查**：當場組出一本含圖片頁的 `.epub` 再轉換，確認目次指到圖片頁時標籤
  會往後落在有文字的那一頁，一個都不會少

No framework, no downloads; it prints `self-test OK`. It covers the output-naming rule,
flat vs mirrored paths, the overwrite policy's memory, visible-text length and the
picture-book thresholds, paragraph indents and the fence escape, blank-line placement,
the book's own contents page, the space read out of the stylesheet (font change, wider
gap, and the poem that is one `<p>` with `<br>` inside it), every link rule (placement,
icon-only links, de-duplication, in-book hrefs, tracking-parameter sweeping), the rules a
book draws with `<hr>` **and** with a border, the cover fence — plus an end-to-end check
that builds a small `.epub` with picture pages and proves a TOC entry pointing at one is
carried to the next page that has text instead of being lost.

---

## 授權 | License

GPL-3.0-or-later。完整條文見 [LICENSE](LICENSE)。

Copyright (C) 2026 Dino9021

This program is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version. It is distributed in
the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.
