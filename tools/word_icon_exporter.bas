Attribute VB_Name = "WordIconExporter"
Option Explicit

Public LastExportImageMsoError As String

Public Function ExportImageMso(ByVal idMso As String, ByVal outputPath As String, ByVal iconSize As Long) As Boolean
    On Error GoTo Failed
    LastExportImageMsoError = ""

    Dim picture As Object
    Set picture = Application.CommandBars.GetImageMso(idMso, iconSize, iconSize)

    If picture Is Nothing Then
        ExportImageMso = False
        Exit Function
    End If

    SavePicture picture, outputPath
    ExportImageMso = (Len(Dir$(outputPath)) > 0)
    Exit Function

Failed:
    LastExportImageMsoError = Err.Number & ": " & Err.Description
    ExportImageMso = False
End Function

Public Function GetLastExportImageMsoError() As String
    GetLastExportImageMsoError = LastExportImageMsoError
End Function
