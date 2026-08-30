import sys

with open('templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

reps = {
    '<button class="btn-primary w-full mt-6">Create course</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Create Course"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg></button>',
    
    '<button class="btn-primary w-full mt-6">Assign course</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Assign Course"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path></svg></button>',
    
    '<button class="btn-primary w-full mt-6">Create assessment</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Create Assessment"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg></button>',
    
    '<button class="btn-primary w-full mt-6">Add question</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Add Question"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg></button>',
    
    '<button class="btn-primary w-full mt-6">Upload questions</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Upload Questions"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg></button>',
    
    '<button class="btn-primary w-full mt-6">Add user</button>': '<button class="btn-primary w-full mt-6 flex justify-center py-3.5" title="Add User"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"></path></svg></button>'
}

for k, v in reps.items():
    content = content.replace(k, v)

with open('templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
