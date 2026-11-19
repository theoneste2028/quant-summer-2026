/**
 * Builds the Quant Summer 2026 user manual as a .docx
 */
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  TableOfContents, PageBreak, Header, Footer, PageNumber, LevelFormat,
  TabStopType, TabStopPosition, LeaderType, Tab,
  convertInchesToTwip, PageOrientation, ExternalHyperlink,
} = require("docx");

/* ------------------------------------------------------------------ */
/* Design tokens                                                       */
/* ------------------------------------------------------------------ */
const INK = "1A1D23";
const MUTED = "5C6472";
const RULE = "D5D7D3";
const ACCENT = "8A4B24";      // burnt amber, matches the results page
const CODEBG = "F2F2EF";
const WARNBG = "FBF3EC";
const OKBG = "EDF3EE";

const BODY = "Calibri";
const MONO = "Consolas";

const PAGE_W = 12240, PAGE_H = 15840;         // US Letter, DXA
const MARGIN = convertInchesToTwip(1);
const CONTENT_W = PAGE_W - MARGIN * 2;        // 8496

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
const P = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 140, line: 288 },
  alignment: opts.align,
  indent: opts.indent,
  children: [new TextRun({
    text, font: BODY, size: opts.size ?? 22,
    color: opts.color ?? INK, bold: opts.bold, italics: opts.italics,
  })],
});

// Paragraph from mixed runs: ["plain", ["bold bit", {bold:true}], ...]
const RP = (parts, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 140, line: 288 },
  indent: opts.indent,
  children: parts.map((p) => {
    if (typeof p === "string") {
      return new TextRun({ text: p, font: BODY, size: 22, color: INK });
    }
    const [t, o = {}] = p;
    return new TextRun({
      text: t,
      font: o.code ? MONO : BODY,
      size: o.code ? 19 : 22,
      color: o.color ?? INK,
      bold: o.bold, italics: o.italics,
    });
  }),
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 420, after: 200 },
  children: [new TextRun({ text, font: BODY, size: 34, bold: true, color: INK })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 320, after: 140 },
  children: [new TextRun({ text, font: BODY, size: 26, bold: true, color: INK })],
});

const H3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 240, after: 100 },
  children: [new TextRun({ text, font: BODY, size: 23, bold: true, color: ACCENT })],
});

const EYEBROW = (text) => new Paragraph({
  spacing: { before: 40, after: 60 },
  children: [new TextRun({
    text: text.toUpperCase(), font: BODY, size: 16, bold: true,
    color: MUTED, characterSpacing: 30,
  })],
});

/** Monospaced command block with a tinted background. */
const CODE = (lines, opts = {}) => {
  const arr = Array.isArray(lines) ? lines : [lines];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    borders: {
      top:    { style: BorderStyle.SINGLE, size: 1, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 1, color: RULE },
      left:   { style: BorderStyle.SINGLE, size: 8, color: opts.accent ?? ACCENT },
      right:  { style: BorderStyle.SINGLE, size: 1, color: RULE },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideVertical:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: opts.fill ?? CODEBG, color: "auto" },
        margins: { top: 130, bottom: 130, left: 170, right: 140 },
        children: arr.map((l, i) => new Paragraph({
          spacing: { after: i === arr.length - 1 ? 0 : 60, line: 260 },
          children: [new TextRun({
            text: l, font: MONO, size: 18,
            color: l.startsWith("#") ? MUTED : INK,
          })],
        })),
      })],
    })],
  });
};

/** Callout box: note / warning / tip. */
const CALLOUT = (label, lines, tone = "note") => {
  const fill = tone === "warn" ? WARNBG : tone === "ok" ? OKBG : CODEBG;
  const bar  = tone === "warn" ? "B4622F" : tone === "ok" ? "3F7A5E" : MUTED;
  const arr = Array.isArray(lines) ? lines : [lines];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    borders: {
      top:    { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      left:   { style: BorderStyle.SINGLE, size: 12, color: bar },
      right:  { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideVertical:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill, color: "auto" },
        margins: { top: 140, bottom: 140, left: 180, right: 160 },
        children: [
          new Paragraph({
            spacing: { after: 70 },
            children: [new TextRun({
              text: label.toUpperCase(), font: BODY, size: 16, bold: true,
              color: bar, characterSpacing: 24,
            })],
          }),
          ...arr.map((t, i) => new Paragraph({
            spacing: { after: i === arr.length - 1 ? 0 : 90, line: 280 },
            children: [new TextRun({ text: t, font: BODY, size: 21, color: INK })],
          })),
        ],
      })],
    })],
  });
};

/** Data table. cols = [{w, label}], rows = [[..], ..]
 *  Column widths are normalised so they always sum to exactly the text width.
 *  Hand-authored widths drift, and a table narrower than the code blocks around
 *  it reads as a mistake — so the last column absorbs any rounding difference.
 */
const TABLE = (cols, rows, opts = {}) => {
  const raw = cols.map((c) => c.w);
  const scale = CONTENT_W / raw.reduce((a, b) => a + b, 0);
  const widths = raw.map((w) => Math.round(w * scale));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const mk = (text, o = {}) => new Paragraph({
    spacing: { after: 0, line: 260 },
    alignment: o.align,
    children: [new TextRun({
      text: String(text), font: o.code ? MONO : BODY,
      size: o.code ? 17 : 20, bold: o.bold,
      color: o.color ?? INK,
    })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    borders: {
      top:    { style: BorderStyle.SINGLE, size: 2, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      left:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right:  { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: RULE },
      insideVertical:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: cols.map((c, i) => new TableCell({
          width: { size: widths[i], type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: "EFEFEC", color: "auto" },
          margins: { top: 90, bottom: 90, left: 130, right: 130 },
          children: [mk(c.label, { bold: true, color: MUTED, align: c.align })],
        })),
      }),
      ...rows.map((r) => new TableRow({
        children: r.map((cell, i) => new TableCell({
          width: { size: widths[i], type: WidthType.DXA },
          margins: { top: 90, bottom: 90, left: 130, right: 130 },
          children: [mk(cell, {
            code: opts.codeCols?.includes(i),
            align: cols[i].align,
            bold: opts.boldCols?.includes(i),
          })],
        })),
      })),
    ],
  });
};

const BULLET = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level },
  spacing: { after: 90, line: 280 },
  children: [new TextRun({ text, font: BODY, size: 22, color: INK })],
});

const NUM = (text, level = 0) => new Paragraph({
  numbering: { reference: "steps", level },
  spacing: { after: 110, line: 280 },
  children: [new TextRun({ text, font: BODY, size: 22, color: INK })],
});

const SPACER = (h = 120) => new Paragraph({ spacing: { after: h }, children: [] });
const BREAK = () => new Paragraph({ children: [new PageBreak()] });

/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */
const cover = [
  // Several empty paragraphs rather than one large `before` value: Word honours
  // leading space on the first paragraph of a page inconsistently, and Pages
  // collapses it entirely, which pinned the title to the top of the page.
  ...Array.from({ length: 7 }, () =>
    new Paragraph({ spacing: { after: 200 }, children: [] })),
  new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({
      text: "USER MANUAL", font: BODY, size: 20, bold: true,
      color: MUTED, characterSpacing: 60,
    })],
  }),
  new Paragraph({
    spacing: { after: 200 },
    children: [new TextRun({
      text: "Quant Summer 2026", font: BODY, size: 62, bold: true, color: INK,
    })],
  }),
  new Paragraph({
    spacing: { after: 420 },
    children: [new TextRun({
      text: "A portfolio research platform — what it does, how to run it, and why it is built this way",
      font: BODY, size: 26, color: MUTED,
    })],
  }),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    borders: {
      top: { style: BorderStyle.SINGLE, size: 6, color: ACCENT },
      bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        margins: { top: 220, bottom: 0, left: 0, right: 0 },
        children: [
          P("Written for someone who has never seen this project before.", { color: MUTED, after: 60 }),
          P("No finance background assumed. No programming background assumed", { color: MUTED, after: 60 }),
          P("beyond being willing to type commands into a terminal.", { color: MUTED, after: 260 }),
          P("Version 1.0  ·  August 2026", { color: MUTED, size: 20 }),
        ],
      })],
    })],
  }),
  BREAK(),
];

/* The contents list is built by hand rather than with a Word TOC field.
 * A field has to be refreshed by the reader (Word: F9) and renders as raw
 * placeholder text in Pages, Google Docs and most previewers — the last thing
 * a manual for a beginner should open with. Page numbers come from a real
 * render of the first pass; see PAGEMAP below. */
const TOC_ENTRIES = [
  ["1.", "What this is", 1],
  ["1.1", "What it actually does, in order", 2],
  ["1.2", "What you get at the end", 2],
  ["2.", "Before you start", 1],
  ["2.1", "A terminal", 2],
  ["2.2", "Python", 2],
  ["2.3", "About 1 GB of free disk space", 2],
  ["3.", "Installing it", 1],
  ["3.1", "Get the code", 2],
  ["3.2", "Create an isolated environment", 2],
  ["3.3", "Install the libraries", 2],
  ["3.4", "Check that it worked", 2],
  ["4.", "Running the tool", 1],
  ["4.1", "The demo path — no data required", 2],
  ["4.2", "The real path — using your own portfolio", 2],
  ["4.3", "Running the main tool", 2],
  ["4.4", "Building the results web page", 2],
  ["5.", "The ten projects", 1],
  ["6.", "Reading the output", 1],
  ["6.1", "Stage 1 — Data", 2],
  ["6.2", "Stage 2 — Statistics", 2],
  ["6.3", "Stage 3 — Optimization", 2],
  ["6.4", "Stage 4 — Decision", 2],
  ["6.5", "Stage 5 — Simulation", 2],
  ["6.6", "The final comparison", 2],
  ["7.", "Why it is built this way", 1],
  ["7.1", "Why the tool reads a database instead of downloading prices", 2],
  ["7.2", "Why the historical averages are deliberately distorted", 2],
  ["7.3", "Why it asks for your risk tolerance", 2],
  ["7.4", "Why risk is reported two different ways", 2],
  ["7.5", "Why there are 603 automated tests", 2],
  ["8.", "When something goes wrong", 1],
  ["8.1", "Starting over", 2],
  ["9.", "Glossary", 1],
  ["9.1", "Where to read more", 2],
];

// Filled in by the second build pass from a rendered PDF; empty on pass one.
let PAGEMAP = {};
try { PAGEMAP = JSON.parse(fs.readFileSync("pagemap.json", "utf8")); } catch (e) {}

/* Laid out as a borderless two-column table rather than with a right tab stop
 * and dot leader. The tab-stop approach is conventional and produces correct
 * OOXML, but Pages (and some other readers) ignore the stop entirely and render
 * the page number jammed against the title. A table positions both columns
 * identically in every renderer. */
const PAGECOL = 700;
const tocRow = ([num, title, lvl]) => new TableRow({
  children: [
    new TableCell({
      width: { size: CONTENT_W - PAGECOL, type: WidthType.DXA },
      margins: {
        top: lvl === 1 ? 140 : 34, bottom: lvl === 1 ? 44 : 34,
        left: lvl === 1 ? 0 : 340, right: 100,
      },
      children: [new Paragraph({
        spacing: { after: 0, line: 250 },
        children: [new TextRun({
          text: `${num}  ${title}`,
          font: BODY, size: lvl === 1 ? 22 : 21,
          bold: lvl === 1, color: lvl === 1 ? INK : MUTED,
        })],
      })],
    }),
    new TableCell({
      width: { size: PAGECOL, type: WidthType.DXA },
      margins: { top: lvl === 1 ? 140 : 34, bottom: lvl === 1 ? 44 : 34, left: 0, right: 0 },
      children: [new Paragraph({
        spacing: { after: 0, line: 250 },
        alignment: AlignmentType.RIGHT,
        children: [new TextRun({
          text: PAGEMAP[`${num} ${title}`] !== undefined
            ? String(PAGEMAP[`${num} ${title}`]) : "",
          font: BODY, size: lvl === 1 ? 22 : 21,
          bold: lvl === 1, color: lvl === 1 ? INK : MUTED,
        })],
      })],
    }),
  ],
});

const NOBORDER = {
  top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};

const toc = [
  H1("Contents"),
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W - PAGECOL, PAGECOL],
    borders: NOBORDER,
    rows: TOC_ENTRIES.map(tocRow),
  }),
  BREAK(),
];

const part1 = [
  H1("1. What this is"),

  P("This software answers a question that is surprisingly hard to answer about your own money: given what you actually own, are you being paid enough for the risk you are taking, and would a different mix of the same kinds of investments do better?"),

  P("It answers that by reading a real brokerage transaction history, working out what you own and what it is worth, measuring how those investments have behaved, and then computing a recommended mix. It finishes by simulating a year into the future to say how likely a bad outcome is."),

  P("It was built over twelve weeks as coursework consolidating three university subjects — probability, database engineering, and engineering economics — so alongside the finished tool there are ten smaller projects, each demonstrating one technique. You can run any of them independently."),

  H2("1.1 What it actually does, in order"),

  P("The finished tool is a pipeline: five stages, each feeding the next. Nothing is magic, and every stage is a file you can open and read."),

  TABLE(
    [{ w: 900, label: "Stage" }, { w: 2400, label: "What happens" }, { w: 5196, label: "Why this stage exists" }],
    [
      ["1", "Data", "Reads your trades and daily prices from a local database. It never calls the internet at this point, so the same input always produces the same output."],
      ["2", "Statistics", "Measures the average return and the risk of each investment, and how they move together. Also checks whether the returns follow the bell curve everyone assumes (they do not)."],
      ["3", "Optimization", "Computes the best possible mixes — for every level of risk, the mix with the highest expected return. This produces a curve called the efficient frontier."],
      ["4", "Decision", "The curve is a menu, not an answer. This stage picks one point on it, based on how much risk you personally are willing to carry."],
      ["5", "Simulation", "Plays the chosen mix forward through 100,000 simulated years to estimate the chance of losing money, and how bad the worst cases get."],
    ],
    { boldCols: [1] }
  ),

  SPACER(200),

  H2("1.2 What you get at the end"),

  P("Three things:"),
  BULLET("A recommended allocation — a list of investments and what percentage of the portfolio each should be."),
  BULLET("A comparison against what you currently hold, on expected return, risk, and the probability of a significant loss."),
  BULLET("A web page presenting all of it with charts, which you can publish or keep to yourself."),

  SPACER(120),

  CALLOUT("Important", [
    "This is a coursework project and a demonstration of technique. It is not investment advice, and it is not a product. Its own output includes a list of limitations, and you should read them before taking any of it seriously.",
  ], "warn"),

  BREAK(),
];

const part2 = [
  H1("2. Before you start"),

  P("You need three things. If you already have them, skip to section 3."),

  H2("2.1 A terminal"),

  P("A terminal is a window where you type commands instead of clicking. On a Mac, press Command+Space, type “Terminal”, and press Enter. On Windows, search for “PowerShell”. On Linux you already know."),

  P("Everything in this manual is a line you type into that window followed by Enter. When you see a shaded box, that is what to type."),

  H2("2.2 Python"),

  P("Python is the programming language this is written in. You need version 3.11 or newer. To find out whether you have it, type:"),

  CODE("python3 --version"),

  SPACER(140),

  P("If that prints something like Python 3.13.5, you are fine. If it says “command not found”, install Python from python.org — take the latest version and accept the defaults."),

  CALLOUT("Note", [
    "This project was developed and tested on Python 3.13.5 on macOS. Anything from 3.11 up should work. Older versions will fail, because the code uses newer syntax.",
  ]),

  H2("2.3 About 1 GB of free disk space"),

  P("The project itself is small. One optional exercise (the database speed benchmark in section 5.8) downloads a public dataset of about three million taxi journeys, which becomes a 500 MB file. You can skip that exercise, and if you do, the whole thing needs less than 100 MB."),

  BREAK(),
];

const part3 = [
  H1("3. Installing it"),

  P("Four commands. Type each one and press Enter, waiting for it to finish before the next."),

  H2("3.1 Get the code"),

  CODE([
    "git clone https://github.com/theoneste2028/quant-summer-2026.git",
    "cd quant-summer-2026",
  ]),

  SPACER(140),

  P("The first line downloads the project. The second moves you into its folder — every later command assumes you are inside it."),

  H2("3.2 Create an isolated environment"),

  CODE([
    "python3 -m venv .venv",
    "source .venv/bin/activate",
  ]),

  SPACER(140),

  RP([
    "This creates a private workspace for the project’s dependencies. It matters because the project needs specific versions of several libraries, and installing those globally can break other Python software on your machine. After the second line, your terminal prompt gains a ",
    ["(.venv)", { code: true }],
    " prefix — that is how you know it is active.",
  ]),

  CALLOUT("Windows users", [
    "The second command is different on Windows. Use:  .venv\\Scripts\\activate",
    "Everything else in this manual is identical.",
  ]),

  H2("3.3 Install the libraries"),

  CODE("pip install -r requirements.txt"),

  SPACER(140),

  P("This reads the list of required libraries and downloads them. It takes two to five minutes and prints a great deal of text. That is normal. It is finished when your prompt returns."),

  H2("3.4 Check that it worked"),

  CODE("python run_all_tests.py"),

  SPACER(140),

  P("This runs every automated check in the project — 603 of them — and takes about 30 seconds. You should see a summary table ending like this:"),

  CODE([
    "W11 capstone                       OK       78       0      11.8",
    "------------------------------------------------------------------",
    "TOTAL                                      603       0      26.6",
  ], { fill: OKBG, accent: "3F7A5E" }),

  SPACER(140),

  RP([
    "The important number is the ",
    ["0", { bold: true }],
    " in the failed column. If you see that, the installation is correct and everything in this manual will work.",
  ]),

  CALLOUT("Why start by running tests", [
    "It seems like a strange first step, but it is the fastest way to find out whether your installation is sound. Every other command in this manual depends on the same libraries. If something is broken — a missing library, an incompatible Python version — this tells you immediately and specifically, rather than failing confusingly ten minutes later.",
  ]),

  BREAK(),
];

const part4 = [
  H1("4. Running the tool"),

  P("There are two paths through this project, and which one you take depends on whether you have your own brokerage data."),

  TABLE(
    [{ w: 2600, label: "Path" }, { w: 3000, label: "What you need" }, { w: 2896, label: "What you can run" }],
    [
      ["Demo", "Nothing. Sample data is included.", "Sections 5.1 to 5.6, and 5.8 to 5.10."],
      ["Your own portfolio", "A CSV transaction export from your broker.", "Everything, including the main capstone tool."],
    ],
    { boldCols: [0] }
  ),

  SPACER(220),

  H2("4.1 The demo path — no data required"),

  P("This builds a small sample database from seven fictional trades so you can see the machinery work:"),

  CODE([
    "python projects/05-portfolio-database/build_db.py --demo",
    "",
    "python projects/05-portfolio-database/dashboard.py positions \\",
    "    --db data/portfolio_demo.db",
  ]),

  SPACER(140),

  P("The first command builds the sample database and prints a set of checks confirming that invalid data is rejected. The second lists the positions it contains. You will see three holdings."),

  CALLOUT("What the demo cannot do", [
    "The demo database deliberately contains only a few investments and about six months of invented prices. That is far too little to estimate risk from, so the main capstone tool will refuse to run against it and will tell you so. This is intentional — a tool that produced confident numbers from that little data would be lying to you.",
  ]),

  H2("4.2 The real path — using your own portfolio"),

  P("You need a transaction history from your broker as a CSV file. In Fidelity, this is under Accounts → Activity → Download. Other brokers have an equivalent; the file needs one row per transaction with a symbol, date, quantity, and price."),

  P("Put that file somewhere you can find it, then run:"),

  CODE([
    "python projects/05-portfolio-database/build_db.py ~/Downloads/Accounts_History.csv",
  ]),

  SPACER(140),

  P("Replace the path with wherever your file actually is. This reads every transaction, works out which securities you hold, downloads two years of daily prices for each from Yahoo Finance, and stores everything in a local database file. It takes a minute or two, mostly waiting on price downloads."),

  P("You will see a summary at the end confirming how many trades and price records were loaded, followed by a list of constraint checks. Every one should say “rejected” — those are deliberate attempts to insert invalid data, proving the database refuses it."),

  H2("4.3 Running the main tool"),

  CODE("python projects/11-capstone-platform/capstone.py"),

  SPACER(140),

  P("This is the capstone. It takes roughly a minute and prints its five stages as it goes. Section 6 explains how to read the output. It also writes five charts into projects/11-capstone-platform/results/."),

  P("To see how the recommendation changes for someone more or less cautious than the default, pass a different risk tolerance in dollars:"),

  CODE([
    "# a cautious investor: willing to risk about $2,000",
    "python projects/11-capstone-platform/capstone.py --risk 2000",
    "",
    "# an aggressive one",
    "python projects/11-capstone-platform/capstone.py --risk 40000",
  ]),

  H2("4.4 Building the results web page"),

  CODE([
    "python projects/11-capstone-platform/export_results.py",
    "python site/build_page.py",
  ]),

  SPACER(140),

  RP([
    "The first command computes the results and saves them as a data file. The second turns that into ",
    ["site/capstone.html", { code: true }],
    " — a single self-contained web page you can double-click to open in any browser, publish to a website, or email to someone.",
  ]),

  CALLOUT("Your account balance is hidden by default", [
    "The web page and the charts show values indexed to a base of 100 rather than real dollars. Every percentage, ratio and conclusion is identical either way — only the scale is withheld — so the analysis is fully demonstrable without publishing what your portfolio is worth.",
    "If you want real amounts, add --absolute to the export command.",
  ], "ok"),

  BREAK(),
];

const part5 = [
  H1("5. The ten projects"),

  P("Beyond the main tool, the repository contains ten self-contained projects. Each one demonstrates a technique and can be run on its own. Every command below assumes you are in the project’s root folder with the environment active."),

  P("They are listed in the order they were built, because each one uses something from the previous."),

  H2("5.1 Distribution fitting — are returns really bell-curved?"),

  P("Almost every financial model assumes daily returns follow a normal distribution — the bell curve. This tests that assumption against real market data by fitting three candidate distributions and scoring which fits best."),

  CODE("python projects/01-distribution-fitting/distribution_fitting.py"),

  SPACER(120),

  P("Result: the bell curve loses on every investment tested. Real markets produce extreme days far more often than it predicts. This matters because it means standard risk estimates are too optimistic — and it is the reason the capstone reports its risk two different ways."),

  H2("5.2 Blackjack probability engine"),

  P("Computes card-game probabilities two independent ways — by exact mathematics, and by simulating a million hands — and checks they agree."),

  CODE("python projects/02-blackjack-probability/blackjack.py"),

  SPACER(120),

  P("This exists to build trust in simulation. When exact maths and simulation agree to three decimal places on a problem where both are possible, you can rely on simulation later for problems where exact maths is not."),

  H2("5.3 Monte Carlo option pricer"),

  P("Prices financial options by simulating thousands of possible futures, then checks the answer against the exact formula where one exists."),

  CODE("python projects/03-monte-carlo-pricer/pricer.py"),

  SPACER(120),

  P("All twelve test cases land within the simulation’s margin of error. The same simulation engine is reused by the capstone to project your portfolio forward."),

  H2("5.4 Option extensions and Bayesian updating"),

  P("Extends the pricer to instruments that have no exact formula, and adds a technique that makes the simulation more accurate for the same amount of computation."),

  CODE("python projects/04-options-extensions/options_extensions.py"),

  H2("5.5 Portfolio database"),

  P("The foundation everything else reads from. Covered in section 4."),

  CODE("python projects/05-portfolio-database/build_db.py --demo"),

  H2("5.6 Portfolio analytics"),

  P("Runs nine analytical queries against your database: what you hold, what it cost, what you have made and lost, your exposure by sector, and your dividend income by quarter."),

  CODE([
    "python projects/05-portfolio-database/dashboard.py           # everything",
    "python projects/05-portfolio-database/dashboard.py positions # one query",
    "python projects/05-portfolio-database/dashboard.py --list    # see the names",
  ]),

  SPACER(120),

  P("This is where the project found that 44.0% of the portfolio sat in one kind of high-risk instrument, spread across seven separate holdings — a concentration invisible when each is viewed on its own."),

  H2("5.7 Transaction safety demonstration"),

  P("Shows what a database guarantees when something goes wrong halfway through recording a trade."),

  CODE("python projects/05-portfolio-database/transactions.py"),

  H2("5.8 Database speed benchmark"),

  CALLOUT("This one downloads 48 MB and creates a 500 MB file", [
    "It uses a public dataset of about three million New York taxi journeys. Skip it if you are short on disk space — nothing else depends on it.",
  ], "warn"),

  CODE([
    "python projects/08-query-optimization/load_taxi.py   # downloads and loads",
    "python projects/08-query-optimization/benchmark.py   # runs the comparison",
  ]),

  SPACER(120),

  P("Measures how much faster database queries run with an index — from ten times faster down to barely any difference — and what that speed costs in storage and slower writing."),

  H2("5.9 Capital budgeting"),

  P("Decides whether a long-term investment is worth making, using a worked example of a rooftop solar installation."),

  CODE("python projects/09-capital-budgeting/capital_budgeting.py"),

  SPACER(120),

  P("It also identifies which assumption the decision most depends on, and how wrong that assumption can be before the answer flips."),

  H2("5.10 Decision analysis"),

  P("Answers two questions: how much is it worth paying for research before making a decision, and why do people rationally buy insurance at a price above its expected cost."),

  CODE("python projects/10-decision-analysis/decision_analysis.py"),

  BREAK(),
];

const part6 = [
  H1("6. Reading the output"),

  P("The capstone prints its five stages in sequence. This section explains what each number means, in plain terms."),

  H2("6.1 Stage 1 — Data"),

  CODE([
    "LAYER 1 — DATA (from SQLite, no live API calls)",
    "  window            2024-10-22 .. 2026-08-10  (450 days)",
    "  universe          20 assets (9 held, 11 candidates)",
    "  excluded          5 with < 400 days: ASTX(272), IREX(199), ...",
    "  current portfolio 14 positions; 77.7% of its value is modellable",
  ]),

  SPACER(140),

  P("It is analysing 450 trading days across 20 investments: 9 you already own, plus 11 widely held funds offered as alternatives. Five of your holdings were excluded because they have not existed long enough to measure — which means about 22% of your portfolio’s value is not covered. That is reported rather than hidden, because it limits what the comparison can claim."),

  H2("6.2 Stage 2 — Statistics"),

  CODE([
    "  mean shrinkage      58.9% toward 5.31%  (Jorion Bayes-Stein)",
    "  covariance shrinkage 8.3% toward constant correlation 0.42",
    "  normality check     20/20 assets reject the Normal",
  ]),

  SPACER(140),

  P("“Shrinkage” is the important idea here, and section 7.2 explains why it exists. In short: the historical averages are pulled toward a common middle value, because an investment that happened to do brilliantly over the measurement window is unlikely to keep doing so, and an optimizer that believes the raw history will chase exactly those."),

  P("The normality line reports that all 20 investments fail the bell-curve assumption — the finding from section 5.1, reappearing where it matters."),

  H2("6.3 Stage 3 — Optimization"),

  P("This computes the efficient frontier: for every level of risk, the mix with the highest achievable return. It prints the range and identifies the mix with the best return-per-unit-of-risk."),

  P("It also reports a “minimum-variance” portfolio, which uses no return forecasts at all. That is a deliberate benchmark: if a forecast-driven portfolio cannot beat it, the forecasts were not adding anything."),

  H2("6.4 Stage 4 — Decision"),

  CODE([
    "LAYER 4 — DECISION (certainty equivalent, R=$5,882 = 25% of wealth)",
    "  recommended        ret 25.19%, vol 25.28%, Sharpe 0.997, 7 holdings",
    "      GLD    25.00%",
    "      GOOGL  24.68%",
    "      SCHD   23.35%",
  ]),

  SPACER(140),

  TABLE(
    [{ w: 2100, label: "Term" }, { w: 6396, label: "What it means" }],
    [
      ["ret", "Expected return per year, on average, if the past is any guide."],
      ["vol", "Volatility — how much the value swings around. Higher means a bumpier ride in both directions."],
      ["Sharpe", "Return divided by risk. Higher is better. It answers “am I being paid enough for the bumpiness?”"],
      ["R", "Risk tolerance, in dollars. Roughly the largest amount you would stake on a coin flip. Lower means more cautious."],
    ],
    { codeCols: [0], boldCols: [0] }
  ),

  SPACER(200),

  P("The tool then prints a table showing how the recommendation changes across risk tolerances from very cautious to very aggressive. That table is arguably more useful than the single recommendation, because nobody knows their own risk tolerance precisely — you can find the row that sounds like you."),

  H2("6.5 Stage 5 — Simulation"),

  CODE([
    "  expected return             28.42%      29.14%",
    "  P(loss)                      19.3%       19.1%",
    "  P(loss > 10%)                10.0%        9.8%",
    "  5% VaR                      18.01%      17.72%",
    "  1% VaR                      31.00%      30.76%",
  ]),

  SPACER(140),

  TABLE(
    [{ w: 2100, label: "Term" }, { w: 6396, label: "What it means" }],
    [
      ["P(loss)", "The chance of ending the year with less than you started."],
      ["P(loss > 10%)", "The chance of losing more than a tenth of the portfolio."],
      ["5% VaR", "The 1-in-20 bad year. Losses should be no worse than this 95% of the time."],
      ["1% VaR", "The 1-in-100 bad year. A deeper measure of how bad things can get."],
    ],
    { codeCols: [0], boldCols: [0] }
  ),

  SPACER(200),

  P("Two columns are printed because the simulation is run twice: once assuming the bell curve, and once assuming the fatter-tailed reality measured in stage 2. Comparing them tells you how much the assumption matters — and section 7.4 explains the surprising answer."),

  H2("6.6 The final comparison"),

  P("The last block compares your current portfolio against the recommendation on every measure. This is the point of the whole exercise. In the reference run, the recommendation accepts a lower expected return in exchange for 62% less volatility, a better return-per-risk ratio, and a roughly one-third chance of a significant loss compared to before."),

  BREAK(),
];

const part7 = [
  H1("7. Why it is built this way"),

  P("Several design decisions look odd until you know what went wrong without them. Each one here was a response to an actual failure."),

  H2("7.1 Why the tool reads a database instead of downloading prices"),

  P("It would be simpler to fetch prices from the internet each time it runs. It does not, for two reasons."),

  P("The first is repeatability. If the tool downloads fresh data on every run, two runs an hour apart give different answers and you cannot tell whether that is a real change or a bug. Reading from a stored database means the same input always gives the same output."),

  P("The second is that storing the data first lets you validate it. The loader checks every row before it is accepted — prices must be positive, the daily high cannot be below the low, dates cannot be in the future. Bad data is rejected at the door, with a reason, instead of quietly producing a wrong answer weeks later."),

  CALLOUT("What went wrong without this", [
    "An earlier version had an offline demonstration mode that generated invented prices so the project could run without internet. Those invented prices were written into the real database and silently replaced 131 days of genuine market data for five investments. Nothing complained. Every valuation in that period was wrong.",
    "It was found by asking the database a question whose answer was impossible — a query returned a negative number of shares — and tracing back. The demo mode now writes to a completely separate file.",
  ], "warn"),

  H2("7.2 Why the historical averages are deliberately distorted"),

  P("This is the least intuitive decision in the project, and the most important."),

  P("The optimizer needs to know what return to expect from each investment. The obvious source is what each one actually returned over the measurement window. The problem is that the optimizer treats those numbers as facts, when they are estimates — and it will pour money into whichever estimate happens to be highest."),

  P("An estimate is highest for one of two reasons: the investment is genuinely excellent, or it got lucky over that particular window. The optimizer cannot tell the difference, so it systematically selects for luck. This is a well-documented failure with a name: error maximization."),

  CALLOUT("What it looked like here", [
    "Run on the raw historical averages, the optimizer recommended putting 100% of the portfolio into four investments and projected a 124% annual return.",
    "Those four were precisely the four with the highest returns over the measurement window — between 116% and 131% annualised. It had not found four excellent investments. It had found the four noisiest estimates and believed them.",
  ], "warn"),

  P("The fix, called shrinkage, pulls every estimate toward a common middle value. How hard it pulls is computed from the data itself: the shorter the history and the less reliable the differences between investments, the harder the pull. Here it pulled 58.9% of the way, which took the top estimate from 131% down to 57%."),

  P("A second, blunter correction caps any single investment at 25% of the portfolio. That is not statistics — it is the judgement that no estimate is ever good enough to justify betting a quarter of your money on one thing."),

  P("With both in place, the recommendation went from four holdings to seven, and the projected return from an absurd 124% to a merely optimistic 25%."),

  H2("7.3 Why it asks for your risk tolerance"),

  P("The optimizer produces a curve of possible portfolios, not a single answer. Choosing among them requires knowing how much risk is acceptable to you, and there is no way to work that out from market data — it is a fact about a person, not about markets."),

  P("So the tool asks, and then, because nobody knows their own risk tolerance precisely, it also shows how the answer changes across the whole range. You are meant to find yourself on that table rather than trust a single number."),

  H2("7.4 Why risk is reported two different ways"),

  P("Section 5.1 established that real returns produce extreme days far more often than the bell curve predicts. The natural conclusion is that risk estimates based on the bell curve are too optimistic, so the simulation is run both ways to show the difference."),

  P("The surprise is that over a one-year horizon, the difference is almost nothing."),

  P("The reason is a mathematical result called the Central Limit Theorem. A yearly return is the accumulation of 252 daily returns, and adding up many independent random quantities produces something close to a bell curve regardless of the shape of the individual pieces. The extremes wash out."),

  P("So fat tails dominate short-horizon risk — a single day, a single week — and matter progressively less as the horizon lengthens. The tool reports this explicitly, across four horizons."),

  CALLOUT("What this does not mean", [
    "It does not mean long-horizon risk is well behaved. It means the danger over a year is not the shape of individual daily moves but their tendency to cluster — quiet periods followed by violent ones, and investments that fall together precisely when you need them not to.",
    "This simulation assumes each day is independent of the last, so it does not model that clustering at all, and therefore understates long-horizon risk. That limitation is stated in the tool’s own output rather than hidden.",
  ], "warn"),

  H2("7.5 Why there are 603 automated tests"),

  P("Financial code is unusually dangerous because its mistakes look plausible. A program that adds up money wrongly does not crash — it prints a slightly different number, and nothing tells you which one is right."),

  P("So the project checks itself continuously. Roughly half the tests compare against answers worked out by hand or derived from formulas; the rest check properties that must be true of any correct result — money cannot appear from nowhere, a risk measure for a rarer event must be worse, adding an index must never change an answer."),

  P("Four real defects were found this way that reading the code had missed. The most instructive: two database queries sorted results without specifying how to break ties, so adding an index changed which rows the report displayed. Not the order — which rows. That kind of bug appears months later, when someone optimizes the database for an unrelated reason."),

  BREAK(),
];

const part8 = [
  H1("8. When something goes wrong"),

  TABLE(
    [{ w: 3100, label: "What you see" }, { w: 5396, label: "What to do" }],
    [
      ["command not found: python3", "Python is not installed, or not on your PATH. Install it from python.org and open a new terminal window."],
      ["No module named 'pandas'", "The environment is not active, or the libraries are not installed. Run: source .venv/bin/activate, then pip install -r requirements.txt"],
      ["No database at data/portfolio.db", "You have not built one yet. See section 4.1 for the demo, 4.2 for your own data."],
      ["Not enough price history ... to run the optimizer", "You are running the capstone against the demo database, which is too small by design. It needs a real brokerage export — see section 4.2."],
      ["possibly delisted; no price data found", "Harmless. One security in the history no longer trades, so no prices could be downloaded. Everything else proceeds."],
      ["A test fails after you changed something", "Read the failure line — it names what was expected and what happened. Tests failing after an edit usually means the edit was wrong, not the test."],
    ],
    { boldCols: [0] }
  ),

  SPACER(220),

  H2("8.1 Starting over"),

  P("Nothing here is precious. To rebuild the database from scratch, delete it and run the loader again:"),

  CODE([
    "rm data/portfolio.db",
    "python projects/05-portfolio-database/build_db.py ~/Downloads/Accounts_History.csv",
  ]),

  SPACER(140),

  P("Loading the same file twice is safe — the loader recognises transactions it has already recorded and adds nothing. That property is called idempotency, and it exists because an earlier version did not have it and silently duplicated seven trades."),

  BREAK(),
];

const part9 = [
  H1("9. Glossary"),

  P("Terms used in the output, in plain language."),

  TABLE(
    [{ w: 2400, label: "Term" }, { w: 6096, label: "Meaning" }],
    [
      ["Covariance", "A measure of whether two investments move together. The whole benefit of spreading money around comes from owning things that do not."],
      ["Efficient frontier", "The set of best-possible mixes: for each level of risk, the one with the highest expected return."],
      ["FIFO", "First In, First Out. When you sell part of a holding bought at different times, this rule says the oldest shares are sold first — which determines your recorded profit."],
      ["Idempotent", "Safe to run more than once. Running it twice has the same effect as running it once."],
      ["Monte Carlo", "Estimating something by simulating it thousands of times with random inputs and looking at the spread of results."],
      ["Normal distribution", "The bell curve. Convenient, widely assumed, and — as this project measures — a poor description of daily market returns."],
      ["NPV", "Net Present Value. What a series of future cash amounts is worth today, given that money arriving later is worth less."],
      ["Sharpe ratio", "Return divided by risk. Higher means better compensation for the bumpiness endured."],
      ["Shrinkage", "Deliberately pulling estimates toward a common value because extreme estimates are usually more luck than signal. See section 7.2."],
      ["VaR", "Value at Risk. The loss that should only be exceeded in a stated fraction of years — a 5% VaR is the 1-in-20 bad year."],
      ["Volatility", "How much a value swings around its average. The standard measure of investment risk."],
    ],
    { boldCols: [0] }
  ),

  SPACER(260),

  H2("9.1 Where to read more"),

  P("The repository contains four long-form articles, one per phase of the project, explaining the reasoning and the things that went wrong. They are in the writeups folder and are written for a general reader:"),

  BULLET("phase-1-probability.md — testing the bell-curve assumption"),
  BULLET("phase-2-data-management.md — what the database found"),
  BULLET("phase-3-decisions.md — why expected value is the wrong rule"),
  BULLET("phase-4-capstone.md — building the optimizer, and its failure"),

  SPACER(160),

  P("Each individual project folder also has a README describing that project alone, and a summary document with its full results."),

  SPACER(260),

  CALLOUT("A closing note", [
    "The most useful thing in this project is not the recommendation it produces. It is the list of things it says it cannot tell you: the measurement window is short and favourable, a fifth of the portfolio could not be modelled, and the simulation assumes calm markets stay calm.",
    "A tool that reports its own limits is more useful than one that sounds certain.",
  ], "ok"),
];

/* ------------------------------------------------------------------ */
const doc = new Document({
  creator: "Quant Summer 2026",
  title: "Quant Summer 2026 — User Manual",
  description: "How to install, run, and understand the portfolio research platform",
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 900, hanging: 260 } } } },
        ],
      },
      {
        reference: "steps",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
        ],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: BODY, size: 22, color: INK } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: PAGE_H, orientation: PageOrientation.PORTRAIT },
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          spacing: { after: 200 },
          children: [new TextRun({
            text: "Quant Summer 2026 — User Manual",
            font: BODY, size: 16, color: MUTED,
          })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 160 },
          children: [new TextRun({
            children: ["Page ", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES],
            font: BODY, size: 16, color: MUTED,
          })],
        })],
      }),
    },
    children: [
      ...cover, ...toc, ...part1, ...part2, ...part3,
      ...part4, ...part5, ...part6, ...part7, ...part8, ...part9,
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  const out = process.argv[2] || "manual.docx";
  fs.writeFileSync(out, buf);
  console.log(`wrote ${out} (${(buf.length / 1024).toFixed(1)} KB)`);
});
