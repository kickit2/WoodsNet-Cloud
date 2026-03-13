const fs = require('fs');
let code = fs.readFileSync('web_portal/app.js', 'utf8');

code = code.replace(/function applySortAndRender\(\) \{/, 'function applySortAndRender() {\n    console.log("--> applySortAndRender START");\n    try {');
code = code.replace(/    renderGallery\(filteredImages\);\n\}/, '    renderGallery(filteredImages);\n    } catch(e) { console.error("!!! ERROR IN applySortAndRender", e); throw e; }\n    console.log("<-- applySortAndRender END");\n}');

code = code.replace(/function renderCharts\(images\) \{/, 'function renderCharts(images) {\n    console.log("--> renderCharts START");\n    try {');
code = code.replace(/    \}\);\n\}/g, '    });\n    } catch(e) { console.error("!!! ERROR IN renderCharts/renderLiveDashboard", e); throw e; }\n    console.log("<-- render END");\n}');

fs.writeFileSync('web_portal/app.js', code);
