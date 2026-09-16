chrome.storage.sync.get({ enginePort: AA_DEFAULT_PORT, autoHighlight: true }, v => {
  document.getElementById("port").value = v.enginePort;
  document.getElementById("auto").checked = v.autoHighlight;
});
document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set({
    enginePort: parseInt(document.getElementById("port").value, 10) || AA_DEFAULT_PORT,
    autoHighlight: document.getElementById("auto").checked
  }, () => { document.getElementById("saved").textContent = "Saved"; setTimeout(() => document.getElementById("saved").textContent = "", 1500); });
});
