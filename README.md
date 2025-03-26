# Bookei
- An AI-powered book generator.
- It can generate thousands of words.
- It can generate really big books.
- It can keep a pretty strong and consistent narrative flow.

A little project I decided to make to start learning python

## How to use?
- Get a Google Gemini API key at https://aistudio.google.com/apikey
- Clone the repo
  ``` bash
  https://github.com/Plinkon/Bookei/
  ```
- Install requirements
  ``` bash
  pip install -r requirements.txt
  ```
- Run `final.py` or `gui.py` (for a GUI)
  ``` bash
  python final.py
  ```

  or for GUI

  ``` bash
  python gui.py
  ```

## Notices:
- Can successfully generate books up to ~80,000 total words with somewhat good narrative flow and with staying on topic all with one API key (free tier)
- Sometimes might generate the same sub-chapter multiple times if there are tons of sub-chapters and chapters
- Usually overshoots words per chapter by a bit, but it's better than less
