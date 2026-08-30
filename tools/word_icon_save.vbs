Option Explicit

Dim args, idMso, outPath, size

Set args = WScript.Arguments

If args.Count <> 3 Then
    WScript.Echo "usage: word_icon_save.vbs <idMso> <output.bmp> <size>"
    WScript.Quit 1
End If

idMso = args(0)
outPath = args(1)
size = CLng(args(2))

Dim wordApp, bars, pic, fs, folder

On Error Resume Next

Set wordApp = CreateObject("Word.Application")
If Err.Number <> 0 Then
    WScript.Echo "WORD_APP_CREATE_FAILED: " & Err.Description
    WScript.Quit 2
End If

wordApp.Visible = False
wordApp.DisplayAlerts = 0

Set bars = wordApp.CommandBars
Set pic = bars.GetImageMso(idMso, size, size)

If Err.Number <> 0 Or pic Is Nothing Then
    WScript.Echo "GET_IMAGE_FAILED: " & Err.Description
    wordApp.Quit
    WScript.Quit 3
End If

Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(outPath)
If Len(folder) > 0 Then
    If Not fs.FolderExists(folder) Then
        fs.CreateFolder folder
    End If
End If

pic.SaveAsFile outPath, True

If Err.Number <> 0 Then
    WScript.Echo "SAVE_IMAGE_FAILED: " & Err.Description
    wordApp.Quit
    WScript.Quit 4
End If

wordApp.Quit
WScript.Quit 0
