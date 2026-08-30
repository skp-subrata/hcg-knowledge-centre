import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

style_start = content.find('<style type="text/tailwindcss">')
style_end = content.find('</style>') + 8

new_style = """<style type="text/tailwindcss">
        @layer utilities {
            .glass-panel {
                @apply bg-white/30 dark:bg-black/30 border border-white/50 dark:border-white/10 rounded-[32px] shadow-[0_8px_32px_rgba(0,0,0,0.06)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.2)] backdrop-blur-2xl backdrop-saturate-[180%];
            }
            .glass-panel-hover {
                @apply hover:bg-white/40 dark:hover:bg-black/40 transition-all duration-300;
            }
            .btn-primary {
                @apply inline-flex items-center justify-center rounded-full bg-slate-900/90 dark:bg-white/90 p-3.5 text-white dark:text-black shadow-lg shadow-black/10 dark:shadow-white/10 hover:bg-slate-800 dark:hover:bg-white hover:scale-105 active:scale-95 transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white disabled:pointer-events-none disabled:opacity-50 backdrop-blur-md;
            }
            .btn-secondary {
                @apply inline-flex items-center justify-center rounded-full border border-slate-200/50 dark:border-slate-700/50 bg-white/40 dark:bg-black/40 p-3.5 text-slate-800 dark:text-slate-200 shadow-sm hover:bg-white/60 dark:hover:bg-black/60 hover:scale-105 active:scale-95 transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-400 disabled:pointer-events-none disabled:opacity-50 backdrop-blur-md;
            }
            .form-input {
                @apply flex h-12 w-full rounded-2xl border border-white/40 dark:border-white/10 bg-white/30 dark:bg-black/30 px-4 py-2 text-sm shadow-inner transition-all file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-slate-500/70 dark:placeholder:text-slate-400/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/50 disabled:cursor-not-allowed disabled:opacity-50 backdrop-blur-md text-slate-900 dark:text-slate-50;
            }
            .form-label {
                @apply text-sm font-semibold tracking-wide text-slate-700 dark:text-slate-300 mb-2 block ml-1;
            }
        }
        
        @keyframes aurora {
            0% { background-position: 0% 0%; }
            50% { background-position: 100% 100%; }
            100% { background-position: 0% 0%; }
        }
        
        body {
            background-color: #e0e7ff;
            background-image: 
                radial-gradient(at 0% 0%, rgba(199,210,254,0.8) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(233,213,255,0.8) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(186,230,253,0.8) 0px, transparent 50%),
                radial-gradient(at 0% 100%, rgba(167,243,208,0.8) 0px, transparent 50%);
            background-size: 200% 200%;
            animation: aurora 15s ease infinite alternate;
            background-attachment: fixed;
        }
        
        .dark body {
            background-color: #0f172a;
            background-image: 
                radial-gradient(at 0% 0%, rgba(30,27,75,1) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(76,29,149,0.8) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(23,37,84,0.8) 0px, transparent 50%),
                radial-gradient(at 0% 100%, rgba(6,78,59,0.8) 0px, transparent 50%);
            background-size: 200% 200%;
            animation: aurora 20s ease infinite alternate;
            background-attachment: fixed;
        }
    </style>"""

content = content[:style_start] + new_style + content[style_end:]
content = content.replace('bg-background dark:bg-darkBackground text-slate-900 dark:text-slate-50 transition-colors duration-200 min-h-screen', 'text-slate-900 dark:text-slate-50 transition-colors duration-500 min-h-screen')

# Also make the navbar more completely glassy/invisible border
content = content.replace('bg-background/95 dark:bg-darkBackground/95', 'bg-white/20 dark:bg-black/20')
content = content.replace('border-border/40 dark:border-darkBorder/40', 'border-white/30 dark:border-white/10')

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated base.html styling.")
