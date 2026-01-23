# Suricato AutoLogin (F12)
**Versão:** 1.1  
**Autor:** Gustavo Pires

## 📋 Descrição
O **Suricato AutoLogin** é uma ferramenta de produtividade projetada para automatizar o preenchimento de credenciais (usuário e senha) através da tecla de atalho **F12**. O sistema foca em segurança, utilizando criptografia AES (Fernet) para proteger os dados sensíveis localmente.

## 🛠️ Tecnologias Utilizadas
* **Python 3**: Linguagem base do núcleo.
* **PyAutoGUI**: Simulação de digitação automatizada.
* **Pynput**: Monitoramento global de teclas (Hook).
* **Cryptography**: Proteção de dados com criptografia de ponta.
* **PyInstaller**: Compilação para executáveis nativos (Windows/Linux).

## 🚀 Como Usar (Usuário Final)
1. Execute o arquivo `autologin.exe` (Windows) ou `autologin` (Linux).
2. Na primeira execução, defina seu Usuário, Senha e uma **Senha Mestra**.
3. O ícone aparecerá na bandeja do sistema (perto do relógio).
4. Em qualquer tela de login, coloque o cursor no campo de usuário e pressione **F12**.

## 🛠️ Manutenção e Build (Desenvolvedor)
Para gerar uma nova versão do executável:

### No Windows:
1. Abra o PowerShell como Administrador na pasta do projeto.
2. Execute: `powershell -ExecutionPolicy Bypass -File autologin_setup.ps1`
3. O script instalará as dependências e criará o atalho na Área de Trabalho.

### No Linux:
1. Abra o terminal na pasta do projeto.
2. Dê permissão de execução: `chmod +x autologin_setup.sh`
3. Execute: `./autologin_setup.sh`

## 🧹 Reset de Fábrica
Caso precise apagar todas as credenciais e configurações:
* **Windows:** Execute o `reset.ps1`.
* **Linux:** Execute o `reset.sh`.